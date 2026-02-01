"""Main crew: router classifies claim, then we run the appropriate workflow crew.

This module orchestrates the claim processing workflow with full observability:
- Structured logging with claim context
- LLM call tracing via callbacks
- Cost and latency metrics per claim
"""

import json
import logging
import threading
import time
from typing import Any

import litellm
from crewai import Crew, Task

from claim_agent.agents.router import create_router_agent
from claim_agent.crews.new_claim_crew import create_new_claim_crew
from claim_agent.crews.duplicate_crew import create_duplicate_crew
from claim_agent.crews.total_loss_crew import create_total_loss_crew
from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew
from claim_agent.crews.partial_loss_crew import create_partial_loss_crew
from claim_agent.config.llm import get_llm, get_model_name
from claim_agent.config.settings import (
    get_crew_verbose,
    MAX_LLM_CALLS_PER_CLAIM,
    MAX_TOKENS_PER_CLAIM,
)
from claim_agent.db.constants import (
    STATUS_CLOSED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_FRAUD_SUSPECTED,
    STATUS_NEEDS_REVIEW,
    STATUS_OPEN,
    STATUS_PARTIAL_LOSS,
    STATUS_PROCESSING,
)
from claim_agent.tools.logic import evaluate_escalation_impl
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput, ClaimType, EscalationOutput
from claim_agent.observability import (
    get_logger,
    claim_context,
    get_metrics,
)
from claim_agent.observability.tracing import LiteLLMTracingCallback
from claim_agent.utils.retry import with_llm_retry
from claim_agent.utils.sanitization import sanitize_claim_data

logger = get_logger(__name__)

# Thread-safe LiteLLM callback management for concurrent claim processing
_callbacks_lock = threading.Lock()


class TokenBudgetExceeded(Exception):
    """Raised when a claim exceeds the configured token or LLM call budget."""

    def __init__(self, claim_id: str, total_tokens: int, total_calls: int, message: str):
        self.claim_id = claim_id
        self.total_tokens = total_tokens
        self.total_calls = total_calls
        super().__init__(message)


def create_router_crew(llm=None):
    """Create a crew with only the router agent to classify the claim."""
    llm = llm or get_llm()
    router = create_router_agent(llm)

    classify_task = Task(
        description="""Classify the following claim based on its data.

CLAIM DATA:
{claim_data}

Classify this claim as exactly one of: new, duplicate, total_loss, fraud, or partial_loss.

- duplicate: If "existing_claims_for_vin" is present and contains claims with similar incident dates (days_difference <= 7) or similar incident descriptions, classify as duplicate. This takes priority over other classifications.
- new: First-time claim submission, standard intake with no red flags. Only use if no existing claims match.
- total_loss: Vehicle damage suggests total loss (e.g. totaled, flood, fire, destroyed, frame damage, or repair would exceed 75% of vehicle value).
- fraud: Claim shows fraud indicators such as staged accident language, inflated damage claims, prior fraud history, inconsistent details, or suspiciously high estimates.
- partial_loss: Vehicle has repairable damage (e.g. bumper, fender, door, dents, scratches, broken lights). The vehicle is NOT totaled and can be repaired.

Guidelines for duplicate detection:
- Check if "existing_claims_for_vin" field exists in the claim data
- If it contains claims with days_difference of 0-7, this is likely a duplicate
- If incident descriptions are similar to existing claims, this is likely a duplicate

Guidelines for partial_loss vs total_loss:
- If damage mentions: bumper, fender, door, mirror, dent, scratch, light, windshield, minor collision -> partial_loss
- If damage mentions: totaled, flood, fire, destroyed, frame damage, rollover, submerged, total loss -> total_loss
- If estimated_damage is moderate (under $10,000 typically), consider partial_loss.

Reply with exactly one word: new, duplicate, total_loss, fraud, or partial_loss. Then on the next line give one sentence reasoning.""",
        expected_output="One line: exactly 'new', 'duplicate', 'total_loss', 'fraud', or 'partial_loss'. Second line: brief reasoning.",
        agent=router,
    )

    return Crew(
        agents=[router],
        tasks=[classify_task],
        verbose=get_crew_verbose(),
    )


def create_main_crew(llm=None):
    """Create the main crew (router only). Use run_claim_workflow to classify and run the right sub-crew."""
    return create_router_crew(llm)


def _parse_claim_type(raw_output: str) -> str:
    """Parse claim type from router output with strict matching."""
    lines = raw_output.strip().split("\n")
    for line in lines:
        normalized = line.strip().lower().replace("_", " ").replace("-", " ")
        # Exact matches first
        if normalized in ("new", "duplicate", "total loss", "total_loss", "partial loss", "partial_loss", "fraud"):
            if normalized in ("total loss", "total_loss"):
                return ClaimType.TOTAL_LOSS.value
            if normalized in ("partial loss", "partial_loss"):
                return ClaimType.PARTIAL_LOSS.value
            if normalized == "new":
                return ClaimType.NEW.value
            if normalized == "duplicate":
                return ClaimType.DUPLICATE.value
            if normalized == "fraud":
                return ClaimType.FRAUD.value
            return normalized
        # Then line starts with type (check fraud, partial_loss, total_loss before duplicate/new)
        if normalized.startswith("fraud"):
            return ClaimType.FRAUD.value
        if normalized.startswith("partial loss") or normalized.startswith("partial_loss"):
            return ClaimType.PARTIAL_LOSS.value
        if normalized.startswith("total loss") or normalized.startswith("total_loss"):
            return ClaimType.TOTAL_LOSS.value
        if normalized.startswith("duplicate"):
            return ClaimType.DUPLICATE.value
        if normalized.startswith("new"):
            return ClaimType.NEW.value
    return ClaimType.NEW.value


def _kickoff_with_retry(crew: Any, inputs: dict[str, Any]) -> Any:
    """Run crew.kickoff with retry on transient failures."""
    @with_llm_retry()
    def _call() -> Any:
        return crew.kickoff(inputs=inputs)

    return _call()


def _check_token_budget(claim_id: str, metrics: Any) -> None:
    """Raise TokenBudgetExceeded if claim exceeds configured token or call budget."""
    summary = metrics.get_claim_summary(claim_id)
    if summary is None:
        return
    if summary.total_tokens > MAX_TOKENS_PER_CLAIM:
        raise TokenBudgetExceeded(
            claim_id,
            summary.total_tokens,
            summary.total_llm_calls,
            f"Token budget exceeded: {summary.total_tokens} > {MAX_TOKENS_PER_CLAIM}",
        )
    if summary.total_llm_calls > MAX_LLM_CALLS_PER_CLAIM:
        raise TokenBudgetExceeded(
            claim_id,
            summary.total_tokens,
            summary.total_llm_calls,
            f"LLM call budget exceeded: {summary.total_llm_calls} > {MAX_LLM_CALLS_PER_CLAIM}",
        )


def _final_status(claim_type: str) -> str:
    """Map claim_type to final claim status."""
    if claim_type == ClaimType.NEW.value:
        return STATUS_OPEN
    if claim_type == ClaimType.DUPLICATE.value:
        return STATUS_DUPLICATE
    if claim_type == ClaimType.FRAUD.value:
        return STATUS_FRAUD_SUSPECTED
    if claim_type == ClaimType.PARTIAL_LOSS.value:
        return STATUS_PARTIAL_LOSS
    return STATUS_CLOSED


def _check_for_duplicates(claim_data: dict, current_claim_id: str | None = None) -> list[dict]:
    """Search for existing claims with same VIN and similar incident date.
    
    Returns list of potential duplicate claims (excluding the current claim if provided).
    """
    vin = claim_data.get("vin", "").strip()
    incident_date = claim_data.get("incident_date", "").strip()
    
    if not vin:
        return []
    
    repo = ClaimRepository()
    # Search by VIN to find all claims for this vehicle
    matches = repo.search_claims(vin=vin, incident_date=None)
    
    # Filter out the current claim if provided
    if current_claim_id:
        matches = [m for m in matches if m.get("id") != current_claim_id]
    
    # If we have an incident date, prioritize claims with matching/close dates
    if incident_date and matches:
        from datetime import datetime, timedelta
        try:
            target_date = datetime.fromisoformat(incident_date)
            for match in matches:
                match_date_str = match.get("incident_date", "")
                try:
                    match_date = datetime.fromisoformat(match_date_str)
                    days_diff = abs((target_date - match_date).days)
                    match["days_difference"] = days_diff
                except (ValueError, TypeError):
                    match["days_difference"] = 999
            # Sort by date proximity
            matches.sort(key=lambda x: x.get("days_difference", 999))
        except (ValueError, TypeError):
            pass
    
    return matches


def run_claim_workflow(claim_data: dict, llm=None, existing_claim_id: str | None = None) -> dict:
    """
    Run the full claim workflow: classify with router crew, then run the appropriate workflow crew.
    Persists claim to SQLite, logs state changes, and saves workflow result.

    This function includes full observability:
    - Structured logging with claim_id context
    - Metrics tracking for cost and latency
    - LLM call tracing via callbacks

    Args:
        claim_data: dict with policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                   incident_date, incident_description, damage_description, estimated_damage (optional).
        llm: Optional LLM instance. If None, uses default from config.
        existing_claim_id: if set, re-run workflow for this claim (no new claim created).

    Returns:
        dict with claim_id, claim_type, summary, and workflow_output. When the claim is
        escalated (needs_review), the dict also includes status (STATUS_NEEDS_REVIEW), escalation_reasons,
        escalation_priority, and workflow_output holds escalation details (JSON). When not escalated,
        the dict has claim_id, claim_type, router_output, workflow_output (crew output), summary.
    """
    workflow_start_time = time.time()

    # Sanitize input to limit prompt injection and abuse
    claim_data = sanitize_claim_data(claim_data)

    llm = llm or get_llm()
    repo = ClaimRepository()
    metrics = get_metrics()

    # Create or retrieve claim
    if existing_claim_id:
        claim_id = existing_claim_id
        if repo.get_claim(claim_id) is None:
            raise ValueError(f"Claim not found: {claim_id}")
        logger.info("Reprocessing existing claim", extra={"claim_id": claim_id})
    else:
        claim_input = ClaimInput(**claim_data)
        claim_id = repo.create_claim(claim_input)
        logger.info(
            "Created new claim",
            extra={
                "claim_id": claim_id,
                "extra_data": {
                    "event": "claim_created",
                    "policy_number": claim_data.get("policy_number"),
                    "vin": claim_data.get("vin"),
                },
            },
        )

    # Start metrics tracking for this claim
    metrics.start_claim(claim_id)

    # Set up claim context for all logging within this block
    with claim_context(
        claim_id=claim_id,
        policy_number=claim_data.get("policy_number"),
    ):
        # Both new and reprocessed claims set to PROCESSING for consistent workflow tracking
        repo.update_claim_status(claim_id, STATUS_PROCESSING)
        logger.log_event("workflow_started", status=STATUS_PROCESSING)

        # Register LiteLLM callback so all LLM calls (via CrewAI) are traced with real token/cost data
        litellm_callback = LiteLLMTracingCallback(
            claim_id=claim_id,
            metrics_collector=metrics,
        )
        with _callbacks_lock:
            prev_litellm_callbacks = list(getattr(litellm, "callbacks", None) or [])
            litellm.callbacks = prev_litellm_callbacks + [litellm_callback]

        try:
            # Pre-check: Search for potential duplicate claims by VIN
            existing_claims = _check_for_duplicates(claim_data, current_claim_id=claim_id)
            
            # Inject claim_id and duplicate info so router can detect duplicates
            claim_data_with_id = {**claim_data, "claim_id": claim_id}
            if existing_claims:
                # Include existing claims info for duplicate detection
                claim_data_with_id["existing_claims_for_vin"] = [
                    {
                        "claim_id": c.get("id"),
                        "incident_date": c.get("incident_date"),
                        "incident_description": c.get("incident_description", "")[:200],
                        "days_difference": c.get("days_difference"),
                    }
                    for c in existing_claims[:5]  # Limit to 5 most relevant
                ]
            inputs = {"claim_data": json.dumps(claim_data_with_id) if isinstance(claim_data_with_id, dict) else claim_data_with_id}

            # Step 1: Classify
            logger.log_event("router_started", step="classification")
            router_start = time.time()

            router_crew = create_router_crew(llm)
            result = _kickoff_with_retry(router_crew, inputs)

            router_latency = (time.time() - router_start) * 1000
            raw_output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
            raw_output = str(raw_output)
            claim_type = _parse_claim_type(raw_output)

            logger.set_claim_type(claim_type)
            logger.log_event(
                "router_completed",
                claim_type=claim_type,
                latency_ms=router_latency,
            )

            _check_token_budget(claim_id, metrics)

            # Step 1b: Escalation check (HITL) — skip for fraud so the fraud crew runs and performs its own assessment
            if claim_type != ClaimType.FRAUD.value:
                escalation_json = evaluate_escalation_impl(
                    claim_data,
                    raw_output,
                    similarity_score=None,
                    payout_amount=None,
                )
                escalation_result = json.loads(escalation_json)
                if escalation_result.get("needs_review"):
                    reasons = escalation_result.get("escalation_reasons", [])
                    priority = escalation_result.get("priority", "low")
                    recommended_action = escalation_result.get("recommended_action", "")
                    fraud_indicators = escalation_result.get("fraud_indicators", [])
                    escalation_output = EscalationOutput(
                        claim_id=claim_id,
                        needs_review=True,
                        escalation_reasons=reasons,
                        priority=priority,
                        recommended_action=recommended_action,
                        fraud_indicators=fraud_indicators,
                    )
                    details = json.dumps({
                        "escalation_reasons": reasons,
                        "priority": priority,
                        "recommended_action": recommended_action,
                        "fraud_indicators": fraud_indicators,
                    })
                    repo.save_workflow_result(claim_id, claim_type, raw_output, details)
                    repo.update_claim_status(claim_id, STATUS_NEEDS_REVIEW, claim_type=claim_type, details=details)

                    workflow_duration = (time.time() - workflow_start_time) * 1000
                    logger.log_event(
                        "claim_escalated",
                        reasons=reasons,
                        priority=priority,
                        duration_ms=workflow_duration,
                    )

                    # End metrics tracking
                    metrics.end_claim(claim_id, status="escalated")
                    metrics.log_claim_summary(claim_id)

                    return {
                        **escalation_output.model_dump(),
                        "claim_type": claim_type,
                        "status": STATUS_NEEDS_REVIEW,
                        "router_output": raw_output,
                        "workflow_output": details,
                        "summary": f"Escalated for review: {', '.join(reasons)}",
                    }

            # Step 2: Run the appropriate crew
            _check_token_budget(claim_id, metrics)
            logger.log_event("crew_started", crew=claim_type)
            crew_start = time.time()

            if claim_type == ClaimType.NEW.value:
                crew = create_new_claim_crew(llm)
            elif claim_type == ClaimType.DUPLICATE.value:
                crew = create_duplicate_crew(llm)
            elif claim_type == ClaimType.FRAUD.value:
                crew = create_fraud_detection_crew(llm)
            elif claim_type == ClaimType.PARTIAL_LOSS.value:
                crew = create_partial_loss_crew(llm)
            else:
                crew = create_total_loss_crew(llm)

            workflow_result = _kickoff_with_retry(crew, inputs)
            _check_token_budget(claim_id, metrics)
            crew_latency = (time.time() - crew_start) * 1000

            workflow_output = getattr(workflow_result, "raw", None) or getattr(workflow_result, "output", None) or str(workflow_result)
            workflow_output = str(workflow_output)

            logger.log_event(
                "crew_completed",
                crew=claim_type,
                latency_ms=crew_latency,
            )

            final_status = _final_status(claim_type)
            repo.save_workflow_result(claim_id, claim_type, raw_output, workflow_output)
            repo.update_claim_status(
                claim_id,
                final_status,
                details=workflow_output[:500] if len(workflow_output) > 500 else workflow_output,
                claim_type=claim_type,
            )

            workflow_duration = (time.time() - workflow_start_time) * 1000
            logger.log_event(
                "workflow_completed",
                status=final_status,
                duration_ms=workflow_duration,
            )

            # End metrics tracking
            metrics.end_claim(claim_id, status=final_status)
            metrics.log_claim_summary(claim_id)

            return {
                "claim_id": claim_id,
                "claim_type": claim_type,
                "router_output": raw_output,
                "workflow_output": workflow_output,
                "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
            }
        except Exception as e:
            details = str(e)
            if len(details) > 500:
                details = details[:500] + "..."
            repo.update_claim_status(claim_id, STATUS_FAILED, details=details)

            workflow_duration = (time.time() - workflow_start_time) * 1000
            logger.log_event(
                "workflow_failed",
                error=details,
                duration_ms=workflow_duration,
                level=logging.ERROR,
            )

            # End metrics tracking with error status
            metrics.end_claim(claim_id, status="error")
            metrics.log_claim_summary(claim_id)

            raise
        finally:
            with _callbacks_lock:
                current_callbacks = list(getattr(litellm, "callbacks", None) or [])
                litellm.callbacks = [cb for cb in current_callbacks if cb is not litellm_callback]
