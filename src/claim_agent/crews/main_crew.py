"""Main crew: router classifies claim, then we run the appropriate workflow crew.

This module orchestrates the claim processing workflow with full observability:
- Structured logging with claim context
- LLM call tracing via callbacks
- Cost and latency metrics per claim
"""

import json
import logging
import re
import threading
import time
from datetime import date
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
from claim_agent.tools.logic import evaluate_escalation_impl, detect_fraud_indicators_impl
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

CLASSIFICATION RULES (in priority order):

1. **duplicate**: ONLY if "existing_claims_for_vin" contains claims with:
   - For standard claims: description_similarity_score >= 40 AND days_difference <= 3 (incident dates within 3 days)
   - For high-value claims ("high_value_claim": true): description_similarity_score >= 60 AND days_difference <= 3
   - In all cases, different damage types on the same VIN are NOT duplicates, even if the above thresholds are met

2. **total_loss**: Classify as total_loss if ANY of these are true:
   - "is_catastrophic_event": true (rollover, fire, flood, etc.)
   - "damage_indicates_total_loss": true (damage description mentions totaled/destroyed/etc.)
   - "is_economic_total_loss": true AND damage description does NOT conflict with minor damage
   - Damage description contains: totaled, flood, fire, destroyed, frame bent, frame damage, rollover, submerged, roof crushed, beyond repair, complete loss, unrepairable

3. **fraud**: ONLY if:
   - "pre_routing_fraud_indicators" is present AND not empty
   - OR incident description conflicts significantly with damage description (minor incident but major damage claimed)
   - BUT: If damage_indicates_total_loss is true with catastrophic keywords, classify as total_loss, NOT fraud
   - High damage-to-value ratio alone is NOT fraud if the damage description supports total loss

4. **partial_loss**: Damage is repairable:
   - Bumper, fender, door, mirror, dent, scratch, light, windshield damage
   - No catastrophic keywords in damage description
   - "damage_is_repairable": true indicates damage to replaceable parts
   - If damage_is_repairable is true AND is_economic_total_loss is false -> partial_loss
   - Even with high damage cost, if only repairable parts are mentioned (doors, panels, etc.) -> partial_loss

5. **new**: First-time claim, unclear damage, or needs assessment. Use only if none of the above apply.

KEY DECISION POINTS:
- If damage says "totaled", "destroyed", "total loss", "beyond repair" -> total_loss (NOT fraud)
- If rollover, fire, or flood mentioned -> total_loss (NOT fraud)
- High damage cost alone without fraud keywords -> check if total_loss first
- For duplicates: Look at both days_difference AND description_similarity_score

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


def _record_crew_llm_usage(claim_id: str, llm: Any, metrics: Any) -> None:
    """Record CrewAI LLM token usage and cost into metrics for this claim.

    CrewAI uses native SDK (OpenAI etc.) for standard models, so LiteLLM callbacks
    are not invoked. The LLM instance accumulates usage via get_token_usage_summary().
    We record one aggregated call so evaluation and reporting get real token/cost data.
    """
    get_usage = getattr(llm, "get_token_usage_summary", None)
    if get_usage is None:
        return
    try:
        usage = get_usage()
    except Exception:
        return
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    if (prompt_tokens + completion_tokens) == 0 and getattr(usage, "successful_requests", 0) == 0:
        return
    model = get_model_name() or getattr(llm, "model", "unknown")
    metrics.record_llm_call(
        claim_id=claim_id,
        model=model,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        cost_usd=None,
        latency_ms=0.0,
        status="success",
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
    incident_date_raw = claim_data.get("incident_date")
    # Handle both date objects and strings
    if isinstance(incident_date_raw, date):
        incident_date = incident_date_raw.isoformat()
    elif isinstance(incident_date_raw, str):
        incident_date = incident_date_raw.strip()
    else:
        incident_date = ""
    
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
        from datetime import datetime
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
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Skipping incident date proximity ranking due to invalid incident_date format: %s",
                incident_date,
                exc_info=exc,
            )

    return matches


# Catastrophic event keywords (incident type: flood, fire, rollover, etc.)
_CATASTROPHIC_EVENT_KEYWORDS = [
    "flood", "flooded", "flooding", "fire", "fires", "submerged", "rollover", "rolled over",
    "roof crushed", "burned", "burning", "burnt",
]
# Explicit total-loss wording (outcome: totaled, destroyed, beyond repair, etc.)
_EXPLICIT_TOTAL_LOSS_KEYWORDS = [
    "totaled", "total loss", "destroyed", "beyond repair",
    "unrepairable", "complete loss", "write-off", "write off",
    "frame bent", "frame damage",
]


def _has_catastrophic_event_keywords(text: str) -> bool:
    """Check if text contains catastrophic event keywords (flood, fire, rollover, etc.)."""
    if not text:
        return False
    text_lower = text.lower()
    # Use word boundary matching to avoid false positives (e.g., "fire" matching "misfired")
    return any(re.search(r'\b' + re.escape(kw) + r'\b', text_lower) for kw in _CATASTROPHIC_EVENT_KEYWORDS)


def _has_explicit_total_loss_keywords(text: str) -> bool:
    """Check if text explicitly mentions total loss (totaled, destroyed, beyond repair, etc.)."""
    if not text:
        return False
    text_lower = text.lower()
    # Use word boundary matching to avoid false positives
    return any(re.search(r'\b' + re.escape(kw) + r'\b', text_lower) for kw in _EXPLICIT_TOTAL_LOSS_KEYWORDS)


def _has_catastrophic_keywords(text: str) -> bool:
    """Check if text contains any total-loss signal (event or explicit outcome)."""
    return _has_catastrophic_event_keywords(text) or _has_explicit_total_loss_keywords(text)


def _has_repairable_damage_keywords(text: str) -> bool:
    """Check if text describes repairable damage (parts that can be replaced)."""
    if not text:
        return False
    text_lower = text.lower()
    repairable_keywords = [
        "door", "doors", "fender", "bumper", "hood", "trunk",
        "mirror", "light", "headlight", "taillight", "dent", "scratch",
        "panel", "quarter panel", "windshield", "window", "paint",
    ]
    # Use word boundary matching to avoid false positives (e.g., "dent" matching "accident")
    has_repairable = any(re.search(r'\b' + re.escape(kw) + r'\b', text_lower) for kw in repairable_keywords)
    has_catastrophic = _has_catastrophic_keywords(text)
    return has_repairable and not has_catastrophic


def _filter_weak_fraud_indicators(indicators: list) -> list:
    """Remove weak fraud indicators that are expected in total-loss or high-damage scenarios.
    Use whenever attaching pre_routing_fraud_indicators so filtering is consistent."""
    weak = {"damage_near_or_above_vehicle_value", "incident_damage_description_mismatch"}
    return [i for i in indicators if i not in weak]


def _check_economic_total_loss(claim_data: dict) -> dict:
    """Check if repair cost exceeds 75% of vehicle value (economic total loss).
    
    Returns additional context:
    - is_economic_total_loss: True when cost >= 75% of value, except when damage is repairable-only
      and ratio < 100% (high cost to replace doors/panels etc. is partial_loss, not economic total).
      At ratio >= 100%, is_economic_total_loss is always True (strict 75% rule with this exception).
    - is_catastrophic_event: True if incident or damage description contains catastrophic event
      keywords (flood, fire, rollover, etc.).
    - damage_indicates_total_loss: True if damage description explicitly mentions total loss or
      contains catastrophic event keywords.
    - damage_is_repairable: True if damage describes repairable parts (doors, bumpers, etc.)
      and no total-loss keywords.
    """
    from claim_agent.tools.logic import fetch_vehicle_value_impl
    from claim_agent.config.settings import PARTIAL_LOSS_THRESHOLD

    damage_desc = claim_data.get("damage_description", "") or ""
    incident_desc = claim_data.get("incident_description", "") or ""

    # Catastrophic events (rollover, fire, flood) often appear in incident_description
    is_catastrophic = _has_catastrophic_event_keywords(incident_desc) or _has_catastrophic_event_keywords(damage_desc)
    # Damage indicates total when it has explicit wording or catastrophic event keywords
    damage_indicates_total = _has_explicit_total_loss_keywords(damage_desc) or _has_catastrophic_event_keywords(damage_desc)
    damage_is_repairable = _has_repairable_damage_keywords(damage_desc)

    estimated_damage = claim_data.get("estimated_damage")
    if estimated_damage is None or not isinstance(estimated_damage, (int, float)) or estimated_damage <= 0:
        return {
            "is_economic_total_loss": False,
            "is_catastrophic_event": is_catastrophic,
            "damage_indicates_total_loss": damage_indicates_total,
            "damage_is_repairable": damage_is_repairable,
        }

    vin = claim_data.get("vin", "") or ""
    year = claim_data.get("vehicle_year", 2020)
    make = claim_data.get("vehicle_make", "") or ""
    model = claim_data.get("vehicle_model", "") or ""

    value_result = json.loads(fetch_vehicle_value_impl(vin, year, make, model))
    vehicle_value = value_result.get("value", 15000)

    threshold = PARTIAL_LOSS_THRESHOLD * vehicle_value
    cost_exceeds_threshold = estimated_damage >= threshold
    ratio = round(estimated_damage / vehicle_value, 2) if vehicle_value > 0 else 0

    # is_economic_total_loss is strictly cost/value-based (75% rule). Do not set True from
    # damage keywords alone; use damage_indicates_total_loss / is_catastrophic_event for that.
    if cost_exceeds_threshold and damage_is_repairable and ratio < 1.0:
        # High cost but damage described as repairable parts only -> lean toward partial_loss
        is_total = False
    else:
        is_total = cost_exceeds_threshold

    return {
        "is_economic_total_loss": is_total,
        "is_catastrophic_event": is_catastrophic,
        "damage_indicates_total_loss": damage_indicates_total,
        "damage_is_repairable": damage_is_repairable,
        "vehicle_value": vehicle_value,
        "damage_to_value_ratio": ratio,
    }


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
            # Pre-check: Economic total loss (75% rule) and catastrophic event detection
            economic_check = _check_economic_total_loss(claim_data)
            claim_data_with_id = {**claim_data, "claim_id": claim_id}
            claim_data_with_id["is_economic_total_loss"] = economic_check.get("is_economic_total_loss", False)
            claim_data_with_id["is_catastrophic_event"] = economic_check.get("is_catastrophic_event", False)
            claim_data_with_id["damage_indicates_total_loss"] = economic_check.get("damage_indicates_total_loss", False)
            claim_data_with_id["damage_is_repairable"] = economic_check.get("damage_is_repairable", False)
            claim_data_with_id["vehicle_value"] = economic_check.get("vehicle_value")
            claim_data_with_id["damage_to_value_ratio"] = economic_check.get("damage_to_value_ratio")

            # Pre-routing fraud indicators for high damage-to-value claims
            # BUT: Skip fraud indicators if this is a catastrophic event (rollover, fire, flood, etc.)
            # Catastrophic events naturally have high damage-to-value ratios and should be total_loss, not fraud
            is_catastrophic = economic_check.get("is_catastrophic_event", False)
            damage_indicates_total = economic_check.get("damage_indicates_total_loss", False)
            
            if (economic_check.get("damage_to_value_ratio") or 0) > 0.9 and not is_catastrophic and not damage_indicates_total:
                fraud_result = detect_fraud_indicators_impl(claim_data)
                try:
                    fraud_data = json.loads(fraud_result)
                except (json.JSONDecodeError, TypeError):
                    fraud_data = {}
                indicators = fraud_data if isinstance(fraud_data, list) else (fraud_data.get("indicators", []) if isinstance(fraud_data, dict) else [])
                if indicators:
                    meaningful_indicators = _filter_weak_fraud_indicators(indicators)
                    if meaningful_indicators:
                        claim_data_with_id["pre_routing_fraud_indicators"] = meaningful_indicators

            # High-value claims: avoid duplicate classification without strong evidence
            est_damage = claim_data.get("estimated_damage")
            vehicle_value = economic_check.get("vehicle_value")
            is_high_value = (
                (est_damage is not None and est_damage > 25000)
                or (vehicle_value is not None and vehicle_value > 50000)
            )
            if is_high_value:
                claim_data_with_id["high_value_claim"] = True

            # Pre-check: Search for potential duplicate claims by VIN
            existing_claims = _check_for_duplicates(claim_data, current_claim_id=claim_id)
            if existing_claims:
                from claim_agent.tools.logic import compute_similarity_score_impl
                current_incident = claim_data.get("incident_description", "") or ""
                current_damage = claim_data.get("damage_description", "") or ""
                current_combined = f"{current_incident} {current_damage}"
                
                enriched_claims = []
                for c in existing_claims[:5]:
                    existing_incident = c.get("incident_description", "") or ""
                    existing_damage = c.get("damage_description", "") or ""
                    existing_combined = f"{existing_incident} {existing_damage}"
                    
                    try:
                        similarity_score = compute_similarity_score_impl(current_combined, existing_combined)
                    except (TypeError, ZeroDivisionError) as e:
                        logger.warning(
                            "Similarity computation failed for claim %s: %s",
                            claim_id,
                            str(e),
                        )
                        similarity_score = 0
                    
                    enriched_claims.append({
                        "claim_id": c.get("id"),
                        "incident_date": c.get("incident_date"),
                        "incident_description": existing_incident[:200],
                        "days_difference": c.get("days_difference"),
                        "description_similarity_score": similarity_score,
                    })
                
                claim_data_with_id["existing_claims_for_vin"] = enriched_claims
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
            # Record CrewAI LLM token usage into metrics (CrewAI uses native SDK, not LiteLLM, so
            # litellm callbacks are not invoked; the LLM instance accumulates usage per workflow)
            _record_crew_llm_usage(claim_id=claim_id, llm=llm, metrics=metrics)
