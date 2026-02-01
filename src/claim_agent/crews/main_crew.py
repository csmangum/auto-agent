"""Main crew: router classifies claim, then we run the appropriate workflow crew.

This module orchestrates the claim processing workflow with full observability:
- Structured logging with claim context
- LLM call tracing via callbacks
- Cost and latency metrics per claim
"""

import json
import logging
import time

from crewai import Crew, Task

from claim_agent.agents.router import create_router_agent
from claim_agent.crews.new_claim_crew import create_new_claim_crew
from claim_agent.crews.duplicate_crew import create_duplicate_crew
from claim_agent.crews.total_loss_crew import create_total_loss_crew
from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew
from claim_agent.crews.partial_loss_crew import create_partial_loss_crew
from claim_agent.config.llm import get_llm, get_model_name
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
from claim_agent.models.claim import ClaimInput, EscalationOutput
from claim_agent.observability import (
    get_logger,
    claim_context,
    get_metrics,
    get_tracing_callback,
)

logger = get_logger(__name__)


def create_router_crew(llm=None):
    """Create a crew with only the router agent to classify the claim."""
    llm = llm or get_llm()
    router = create_router_agent(llm)

    classify_task = Task(
        description="""You are given claim_data (JSON) with: policy_number, vin, vehicle_year, vehicle_make, vehicle_model, incident_date, incident_description, damage_description, and optionally estimated_damage.

Classify this claim as exactly one of: new, duplicate, total_loss, fraud, or partial_loss.

- new: First-time claim submission, standard intake with no red flags.
- duplicate: Likely a duplicate of an existing claim (e.g. same incident reported again).
- total_loss: Vehicle damage suggests total loss (e.g. totaled, flood, fire, destroyed, frame damage, or repair would exceed 75% of vehicle value).
- fraud: Claim shows fraud indicators such as staged accident language, inflated damage claims, prior fraud history, inconsistent details, or suspiciously high estimates.
- partial_loss: Vehicle has repairable damage (e.g. bumper, fender, door, dents, scratches, broken lights). The vehicle is NOT totaled and can be repaired.

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
        verbose=True,
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
                return "total_loss"
            if normalized in ("partial loss", "partial_loss"):
                return "partial_loss"
            return normalized
        # Then line starts with type (check fraud, partial_loss, total_loss before duplicate/new)
        if normalized.startswith("fraud"):
            return "fraud"
        if normalized.startswith("partial loss") or normalized.startswith("partial_loss"):
            return "partial_loss"
        if normalized.startswith("total loss") or normalized.startswith("total_loss"):
            return "total_loss"
        if normalized.startswith("duplicate"):
            return "duplicate"
        if normalized.startswith("new"):
            return "new"
    return "new"


def _final_status(claim_type: str) -> str:
    """Map claim_type to final claim status."""
    if claim_type == "new":
        return STATUS_OPEN
    if claim_type == "duplicate":
        return STATUS_DUPLICATE
    if claim_type == "fraud":
        return STATUS_FRAUD_SUSPECTED
    if claim_type == "partial_loss":
        return STATUS_PARTIAL_LOSS
    return STATUS_CLOSED


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
        repo.update_claim_status(claim_id, STATUS_PROCESSING)
        logger.log_event("workflow_started", status=STATUS_PROCESSING)

        # Get tracing callback for LLM calls
        tracing_callback = get_tracing_callback(
            claim_id=claim_id,
            metrics_collector=metrics,
        )

        try:
            # Inject claim_id so workflow crews use the same ID (e.g. new claim assignment)
            claim_data_with_id = {**claim_data, "claim_id": claim_id}
            inputs = {"claim_data": json.dumps(claim_data_with_id) if isinstance(claim_data_with_id, dict) else claim_data_with_id}

            # Step 1: Classify
            logger.log_event("router_started", step="classification")
            router_start = time.time()

            # Track router LLM call
            trace_id = tracing_callback.log_pre_api_call(
                model=get_model_name(),
                agent="router",
                task="classification",
            )

            router_crew = create_router_crew(llm)
            result = router_crew.kickoff(inputs=inputs)

            router_latency = (time.time() - router_start) * 1000
            raw_output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
            raw_output = str(raw_output)
            claim_type = _parse_claim_type(raw_output)

            # Log router completion
            # NOTE: Token counts are rough estimates (char_count / 4) since CrewAI doesn't
            # expose actual token counts. These should NOT be relied upon for accurate cost
            # tracking. For production use, consider integrating a tokenizer library like
            # tiktoken for OpenAI models or extracting actual counts from response objects.
            tracing_callback.log_post_api_call(
                trace_id=trace_id,
                input_tokens=len(inputs.get("claim_data", "")) // 4,  # Rough estimate
                output_tokens=len(raw_output) // 4,  # Rough estimate
            )

            logger.set_claim_type(claim_type)
            logger.log_event(
                "router_completed",
                claim_type=claim_type,
                latency_ms=router_latency,
            )

            # Step 1b: Escalation check (HITL) — skip for fraud so the fraud crew runs and performs its own assessment
            if claim_type != "fraud":
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
            logger.log_event("crew_started", crew=claim_type)
            crew_start = time.time()

            # Track crew LLM call
            crew_trace_id = tracing_callback.log_pre_api_call(
                model=get_model_name(),
                agent=f"{claim_type}_crew",
                task="processing",
            )

            if claim_type == "new":
                crew = create_new_claim_crew(llm)
            elif claim_type == "duplicate":
                crew = create_duplicate_crew(llm)
            elif claim_type == "fraud":
                crew = create_fraud_detection_crew(llm)
            elif claim_type == "partial_loss":
                crew = create_partial_loss_crew(llm)
            else:
                crew = create_total_loss_crew(llm)

            workflow_result = crew.kickoff(inputs=inputs)
            crew_latency = (time.time() - crew_start) * 1000

            workflow_output = getattr(workflow_result, "raw", None) or getattr(workflow_result, "output", None) or str(workflow_result)
            workflow_output = str(workflow_output)

            # Log crew completion
            # NOTE: Token counts are rough estimates (char_count / 4) since CrewAI doesn't
            # expose actual token counts. These should NOT be relied upon for accurate cost
            # tracking. For production use, consider integrating a tokenizer library like
            # tiktoken for OpenAI models or extracting actual counts from response objects.
            tracing_callback.log_post_api_call(
                trace_id=crew_trace_id,
                input_tokens=len(inputs.get("claim_data", "")) // 4,
                output_tokens=len(workflow_output) // 4,
            )

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

            # Complete any pending traces with error
            # Check if trace_id exists (from router) and complete it
            if 'trace_id' in locals():
                tracing_callback.log_post_api_call(
                    trace_id=trace_id,
                    error=str(e),
                )
            # Check if crew_trace_id exists (from crew) and complete it
            if 'crew_trace_id' in locals():
                tracing_callback.log_post_api_call(
                    trace_id=crew_trace_id,
                    error=str(e),
                )

            # End metrics tracking with error status
            metrics.end_claim(claim_id, status="error")
            metrics.log_claim_summary(claim_id)

            raise
