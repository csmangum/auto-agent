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
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import litellm
from crewai import Crew, Task

from claim_agent.agents.router import create_router_agent
from claim_agent.crews.new_claim_crew import create_new_claim_crew
from claim_agent.crews.duplicate_crew import create_duplicate_crew
from claim_agent.crews.total_loss_crew import create_total_loss_crew
from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew
from claim_agent.crews.partial_loss_crew import create_partial_loss_crew
from claim_agent.crews.settlement_crew import create_settlement_crew
from claim_agent.config.llm import get_llm, get_model_name
from claim_agent.config.settings import (
    get_crew_verbose,
    get_router_config,
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
    STATUS_PROCESSING,
    STATUS_SETTLED,
)
from claim_agent.tools.logic import (
    evaluate_escalation_impl,
    detect_fraud_indicators_impl,
    normalize_claim_type,
    validate_router_classification_impl,
    _parse_router_confidence,
)
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput, ClaimType, EscalationOutput, RouterOutput
from claim_agent.observability import (
    get_logger,
    claim_context,
    get_metrics,
)
from claim_agent.observability.prometheus import record_claim_outcome
from claim_agent.observability.tracing import LiteLLMTracingCallback
from claim_agent.utils.retry import with_llm_retry
from claim_agent.utils.sanitization import sanitize_claim_data

logger = get_logger(__name__)

WORKFLOW_STAGES = ("router", "escalation_check", "workflow", "settlement")

# Thread-safe LiteLLM callback management for concurrent claim processing
_callbacks_lock = threading.Lock()


class TokenBudgetExceeded(Exception):
    """Raised when a claim exceeds the configured token or LLM call budget."""

    def __init__(self, claim_id: str, total_tokens: int, total_calls: int, message: str):
        self.claim_id = claim_id
        self.total_tokens = total_tokens
        self.total_calls = total_calls
        super().__init__(message)


def _normalize_claim_data(claim_data: dict) -> tuple[ClaimInput, dict]:
    """Sanitize and validate claim data, returning model + JSON-safe dict.

    This ensures numeric fields are coerced and extra fields are dropped before
    we pass data to LLM prompts or business logic.
    """
    sanitized = sanitize_claim_data(claim_data)
    claim_input = ClaimInput.model_validate(sanitized)
    normalized = claim_input.model_dump(mode="json")
    return claim_input, normalized


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

0. **definitive_duplicate**: If "definitive_duplicate" is true in the claim data, you MUST classify as duplicate. Do not classify as anything else.

1. **duplicate**: ONLY if "existing_claims_for_vin" contains claims with:
   - For standard claims: description_similarity_score >= 40 AND days_difference <= 3 (incident dates within 3 days)
   - For high-value claims ("high_value_claim": true): description_similarity_score >= 60 AND days_difference <= 3
   - In all cases, different damage types on the same VIN are NOT duplicates, even if the above thresholds are met

2. **total_loss**: Classify as total_loss if ANY of these are true:
   - "is_catastrophic_event": true (rollover, fire, flood, etc.)
   - "damage_indicates_total_loss": true (damage description mentions totaled/destroyed/etc.)
   - "is_economic_total_loss": true AND damage description does NOT conflict with minor damage
   - Damage description contains: totaled, flood, fire, destroyed, frame bent, frame damage, rollover, submerged, roof crushed, beyond repair, complete loss, unrepairable

3. **fraud**: Classify as fraud if:
   - "pre_routing_fraud_indicators" is present AND not empty
   - OR incident description describes a minor event (e.g. "minor bump", "barely tapped", "parking lot bump") AND damage description claims major damage (e.g. "frame damage", "entire front end", "vehicle stripped") — this incident/damage mismatch is fraud
   - Fraud-override phrases in incident text: "minor bump", "barely tapped", "staged", "no witnesses", "cameras not working", "inflated" — when present with conflicting damage or pre_routing_fraud_indicators, prefer fraud
   - EXCEPTION: If damage text contains catastrophic keywords (flood, fire, rollover, submerged), classify as total_loss, NOT fraud
   - High damage-to-value ratio alone is NOT fraud if the damage description supports total loss

4. **partial_loss**: Damage is repairable:
   - Bumper, fender, door, mirror, dent, scratch, light, windshield damage
   - No catastrophic keywords in damage description
   - "damage_is_repairable": true indicates damage to replaceable parts
   - If damage_is_repairable is true AND is_economic_total_loss is false -> partial_loss
   - Even with high damage cost, if only repairable parts are mentioned (doors, panels, etc.) -> partial_loss

5. **new**: First-time claim, unclear damage, or needs assessment. Use only if none of the above apply.

EDGE CASE HINTS:
- Very old vehicles (15+ years) with repair cost > 75% of value are typically total_loss.
- If damage_is_repairable is true and no catastrophic keywords in damage description, prefer partial_loss unless is_economic_total_loss is explicitly true.

KEY DECISION POINTS:
- If definitive_duplicate is true -> duplicate (MUST)
- If damage says "totaled", "destroyed", "total loss", "beyond repair" -> total_loss (NOT fraud)
- If rollover, fire, or flood mentioned in damage -> total_loss (NOT fraud)
- If incident says "minor bump"/"barely tapped"/"staged"/"no witnesses" and damage claims major damage or pre_routing_fraud_indicators present -> fraud (unless damage has catastrophic keywords)
- High damage cost alone without fraud keywords -> check if total_loss first
- For duplicates: Look at both days_difference AND description_similarity_score

Reply with a JSON object containing:
- claim_type: exactly one of new, duplicate, total_loss, fraud, or partial_loss
- confidence: a number from 0.0 to 1.0 indicating your confidence in this classification (1.0 = certain, 0.5 = uncertain)
- reasoning: one sentence explaining your classification""",
        expected_output="JSON: {claim_type, confidence (0.0-1.0), reasoning}",
        agent=router,
        output_pydantic=RouterOutput,
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


def _escalate_low_router_confidence(
    claim_id: str,
    claim_type: str,
    raw_output: str,
    router_confidence: float,
    confidence_threshold: float,
    router_reasoning: str,
    repo: "ClaimRepository",
    logger,
    metrics,
    llm,
    workflow_start_time: float,
    actor_id: str,
) -> None:
    """Persist low router confidence escalation to DB."""
    router_config = get_router_config()
    sla_hours = router_config.get("escalation_sla_hours", 48)
    details = json.dumps({
        "escalation_reasons": ["low_router_confidence"],
        "priority": "medium",
        "recommended_action": "Confirm routing classification. Router confidence below threshold.",
        "fraud_indicators": [],
        "router_confidence": router_confidence,
        "router_confidence_threshold": confidence_threshold,
        "router_claim_type": claim_type,
        "router_reasoning": router_reasoning,
    })
    repo.save_workflow_result(claim_id, claim_type, raw_output, details)
    repo.update_claim_status(
        claim_id, STATUS_NEEDS_REVIEW, claim_type=claim_type, details=details, actor_id=actor_id
    )
    hours = sla_hours
    due_at = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    repo.update_claim_review_metadata(
        claim_id,
        priority="medium",
        due_at=due_at,
        review_started_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )
    workflow_duration = (time.time() - workflow_start_time) * 1000
    logger.log_event(
        "claim_escalated",
        reasons=["low_router_confidence"],
        priority="medium",
        duration_ms=workflow_duration,
    )
    _record_crew_llm_usage(claim_id=claim_id, llm=llm, metrics=metrics)
    metrics.end_claim(claim_id, status="escalated")
    record_claim_outcome(
        claim_id, "escalated", (time.time() - workflow_start_time)
    )
    metrics.log_claim_summary(claim_id)


def _escalate_low_router_confidence_response(
    claim_id: str,
    claim_type: str,
    raw_output: str,
    router_confidence: float,
    confidence_threshold: float,
    router_reasoning: str = "",
) -> dict:
    """Build response dict for low router confidence escalation."""
    details = json.dumps({
        "escalation_reasons": ["low_router_confidence"],
        "priority": "medium",
        "recommended_action": "Confirm routing classification. Router confidence below threshold.",
        "fraud_indicators": [],
        "router_confidence": router_confidence,
        "router_confidence_threshold": confidence_threshold,
        "router_claim_type": claim_type,
        "router_reasoning": router_reasoning,
    })
    return {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "status": STATUS_NEEDS_REVIEW,
        "needs_review": True,
        "escalation_reasons": ["low_router_confidence"],
        "priority": "medium",
        "fraud_indicators": [],
        "router_output": raw_output,
        "workflow_output": details,
        "summary": f"Escalated: router confidence {router_confidence:.2f} below threshold {confidence_threshold}",
    }


def _parse_router_output(result: Any, raw_output: str) -> tuple[str, float, str]:
    """Parse router output into (claim_type, confidence, reasoning).

    Prefers structured output (Pydantic or JSON). Falls back to legacy parsing.
    """
    # 1. Try Pydantic output from tasks_output
    tasks_output = getattr(result, "tasks_output", None)
    if tasks_output and isinstance(tasks_output, list) and len(tasks_output) > 0:
        first_output = getattr(tasks_output[0], "output", None)
        if isinstance(first_output, RouterOutput):
            claim_type = normalize_claim_type(first_output.claim_type)
            confidence = max(0.0, min(1.0, float(first_output.confidence)))
            reasoning = (first_output.reasoning or "").strip()
            return claim_type, confidence, reasoning

    # 2. Try JSON parse from raw output
    try:
        # Handle JSON possibly wrapped in markdown code blocks
        text = raw_output.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            claim_type = normalize_claim_type(parsed.get("claim_type", ""))
            conf_val = parsed.get("confidence")
            if conf_val is not None:
                try:
                    confidence = max(0.0, min(1.0, float(conf_val)))
                except (TypeError, ValueError):
                    confidence = 0.0
            else:
                confidence = 0.0
            reasoning = str(parsed.get("reasoning", "") or "").strip()
            return claim_type, confidence, reasoning
    except (json.JSONDecodeError, TypeError):
        pass

    # 3. Fallback: legacy parsing (no explicit confidence)
    claim_type = _parse_claim_type(raw_output)
    confidence = _parse_router_confidence(raw_output)
    reasoning = raw_output.strip().split("\n", 1)[-1].strip() if "\n" in raw_output else ""
    return claim_type, confidence, reasoning


def _kickoff_with_retry(crew: Any, inputs: dict[str, Any]) -> Any:
    """Run crew.kickoff with retry on transient failures."""
    @with_llm_retry()
    def _call() -> Any:
        return crew.kickoff(inputs=inputs)

    return _call()


def _get_llm_usage_snapshot(llm: Any) -> tuple[int, int, int] | None:
    """Best-effort token usage snapshot from CrewAI LLM."""
    get_usage = getattr(llm, "get_token_usage_summary", None)
    if get_usage is None:
        return None
    try:
        usage = get_usage()
    except Exception as exc:
        logger.debug(
            "Failed to get LLM token usage summary: %s",
            exc,
            exc_info=True,
        )
        return None
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    successful_requests = getattr(usage, "successful_requests", 0) or 0
    # Reject mock objects (e.g. MagicMock) that would break cost calculation
    if not isinstance(prompt_tokens, (int, float)) or not isinstance(completion_tokens, (int, float)):
        return None
    if not isinstance(successful_requests, (int, float)):
        successful_requests = 0
    if (prompt_tokens + completion_tokens) == 0 and successful_requests == 0:
        return None
    return int(prompt_tokens), int(completion_tokens), int(successful_requests or 0)


def _check_token_budget(claim_id: str, metrics: Any, llm: Any | None = None) -> None:
    """Raise TokenBudgetExceeded if claim exceeds configured token or call budget."""
    summary = metrics.get_claim_summary(claim_id)
    total_tokens = summary.total_tokens if summary is not None else 0
    total_calls = summary.total_llm_calls if summary is not None else 0

    # If metrics have no calls yet, fall back to CrewAI LLM usage snapshot.
    if total_tokens == 0 and total_calls == 0 and llm is not None:
        usage = _get_llm_usage_snapshot(llm)
        if usage is not None:
            prompt_tokens, completion_tokens, successful_requests = usage
            total_tokens = prompt_tokens + completion_tokens
            total_calls = successful_requests or (1 if total_tokens > 0 else 0)

    if total_tokens > MAX_TOKENS_PER_CLAIM:
        raise TokenBudgetExceeded(
            claim_id,
            total_tokens,
            total_calls,
            f"Token budget exceeded: {total_tokens} > {MAX_TOKENS_PER_CLAIM}",
        )
    if total_calls > MAX_LLM_CALLS_PER_CLAIM:
        raise TokenBudgetExceeded(
            claim_id,
            total_tokens,
            total_calls,
            f"LLM call budget exceeded: {total_calls} > {MAX_LLM_CALLS_PER_CLAIM}",
        )


def _record_crew_llm_usage(claim_id: str, llm: Any, metrics: Any) -> None:
    """Record CrewAI LLM token usage and cost into metrics for this claim.

    CrewAI uses native SDK (OpenAI etc.) for standard models, so LiteLLM callbacks
    are not invoked. The LLM instance accumulates usage via get_token_usage_summary().
    We record one aggregated call so evaluation and reporting get real token/cost data.
    """
    usage = _get_llm_usage_snapshot(llm)
    if usage is None:
        return
    prompt_tokens, completion_tokens, _successful_requests = usage
    model = getattr(llm, "model", None) or get_model_name()
    # Ensure model is a string (reject MagicMock from mocked LLM)
    if not isinstance(model, str):
        model = get_model_name()
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
    if claim_type in (ClaimType.PARTIAL_LOSS.value, ClaimType.TOTAL_LOSS.value):
        return STATUS_SETTLED
    return STATUS_CLOSED


def _requires_settlement(claim_type: str) -> bool:
    """Return True when the workflow should hand off to the shared settlement crew."""
    return claim_type in (ClaimType.PARTIAL_LOSS.value, ClaimType.TOTAL_LOSS.value)


def _combine_workflow_outputs(primary_output: str, settlement_output: str | None = None) -> str:
    """Combine primary workflow and settlement outputs for persistence and summaries."""
    if not settlement_output:
        return primary_output
    return (
        "Primary workflow output:\n"
        f"{primary_output}\n\n"
        "Settlement workflow output:\n"
        f"{settlement_output}"
    )


def _extract_payout_from_workflow_result(result: Any, claim_type: str) -> float | None:
    """Extract payout_amount from workflow crew result when output_pydantic was used.

    For total_loss and partial_loss, the final task uses output_pydantic. The last
    task's output may be a Pydantic model with payout_amount. Returns None if
    extraction fails (Settlement Crew will infer from workflow_output text).
    """
    if claim_type not in (ClaimType.PARTIAL_LOSS.value, ClaimType.TOTAL_LOSS.value):
        return None
    tasks_output = getattr(result, "tasks_output", None)
    if not tasks_output or not isinstance(tasks_output, list):
        return None
    try:
        last_task = tasks_output[-1]
        output = getattr(last_task, "output", None)
        if output is None:
            return None
        val = None
        if hasattr(output, "payout_amount"):
            val = getattr(output, "payout_amount")
        elif isinstance(output, dict) and "payout_amount" in output:
            val = output["payout_amount"]
        if val is not None and isinstance(val, (int, float)) and val >= 0:
            return float(val)
    except (IndexError, TypeError, AttributeError, KeyError):
        pass
    return None


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
# Damage-type tags for duplicate overlap check (not for total-loss classification).
# "catastrophic" overlaps with _CATASTROPHIC_EVENT_KEYWORDS; used so two flood/fire
# claims on same VIN can match as duplicates.
_DAMAGE_TYPE_TAGS: dict[str, list[str]] = {
    "front": ["front bumper", "front end", "hood", "grille", "headlight", "headlights", "radiator"],
    "rear": ["rear bumper", "rear end", "trunk", "taillight", "taillights", "tail light", "tail lights"],
    "side": ["door", "doors", "side", "fender", "fenders", "quarter panel", "mirror", "mirrors"],
    "glass": ["windshield", "window", "windows", "glass"],
    "roof": ["roof"],
    "interior": ["interior", "seat", "dashboard", "airbag"],
    "undercarriage": ["frame", "suspension", "axle"],
    "engine": ["engine", "motor", "transmission"],
    "catastrophic": ["flood", "fire", "rollover", "submerged", "totaled", "destroyed", "beyond repair", "unrepairable"],
}


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


def _extract_damage_tags(text: str) -> set[str]:
    """Extract coarse damage-type tags from incident/damage text."""
    if not text:
        return set()
    text_lower = text.lower()
    tags: set[str] = set()
    for tag, keywords in _DAMAGE_TYPE_TAGS.items():
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
                tags.add(tag)
                break
    return tags


def _damage_tags_overlap(tags_a: set[str], tags_b: set[str]) -> bool:
    """Return True when both tag sets are non-empty and overlap."""
    if not tags_a or not tags_b:
        return False
    return not tags_a.isdisjoint(tags_b)


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


def _handle_mid_workflow_escalation(
    e: MidWorkflowEscalation,
    *,
    claim_id: str,
    claim_type: str,
    raw_output: str,
    repo: "ClaimRepository",
    logger,
    metrics,
    llm,
    workflow_start_time: float,
    prior_workflow_output: str | None = None,
    actor_id: str | None = None,
    stage: str | None = None,
    payout_amount: float | None = None,
    workflow_run_id: str | None = None,
) -> dict:
    """Build and return an escalation response for a MidWorkflowEscalation.

    When *stage* is provided (e.g. ``"settlement"``), the escalation details
    include that stage, the claim status is updated to ``STATUS_NEEDS_REVIEW``,
    and review metadata (priority / due-at) are persisted.  Without *stage*
    (primary crew escalation), only the workflow result is saved.

    Cleans up any checkpoints for *workflow_run_id* so that a future resume
    does not reuse stale cached outputs from a run that ended in escalation.

    Args:
        e: The ``MidWorkflowEscalation`` exception.
        claim_id: Active claim identifier.
        claim_type: Claim classification (e.g. ``"total_loss"``).
        raw_output: Router/crew raw output captured before the escalation.
        repo: ``ClaimRepository`` instance for persistence.
        logger: Structured logger bound to the current claim context.
        metrics: ``ClaimMetrics`` collector for this claim.
        llm: LLM instance used by the crew (for usage recording).
        workflow_start_time: ``time.time()`` captured at workflow start.
        prior_workflow_output: For settlement-stage escalations, the completed
            primary-crew output to combine with escalation details.
        actor_id: Actor to record in audit log entries.
        stage: Optional stage name (e.g. ``"settlement"``).  When provided the
            claim status and review metadata are updated.
        payout_amount: Optional payout from primary crew; persisted when available
            for settlement-stage escalations so adjusters see it in the claim record.
        workflow_run_id: When set, all checkpoints for this run are deleted so
            future resumes start fresh.
    """
    if workflow_run_id:
        repo.delete_task_checkpoints(claim_id, workflow_run_id)
    details_payload: dict[str, Any] = {
        "escalation": True,
        "mid_workflow": True,
        "reason": e.reason,
        "indicators": e.indicators,
        "priority": e.priority,
    }
    if stage is not None:
        details_payload["stage"] = stage

    escalation_details = json.dumps(details_payload)

    if stage is not None and prior_workflow_output is not None:
        saved_output = _combine_workflow_outputs(prior_workflow_output, escalation_details)
    else:
        saved_output = escalation_details

    repo.save_workflow_result(claim_id, claim_type, raw_output, saved_output)

    if stage is not None:
        # When escalation came from escalate_claim tool, status is already needs_review;
        # avoid duplicate status_change audit and overwriting review timestamps.
        current_claim = repo.get_claim(claim_id)
        current_status = current_claim.get("status") if current_claim else None
        if current_status != STATUS_NEEDS_REVIEW:
            repo.update_claim_status(
                claim_id,
                STATUS_NEEDS_REVIEW,
                claim_type=claim_type,
                details=escalation_details,
                payout_amount=payout_amount,
                actor_id=actor_id,
            )
            hours = 24 if e.priority in ("critical", "high") else 48 if e.priority == "medium" else 72
            due_at = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            repo.update_claim_review_metadata(
                claim_id,
                priority=e.priority,
                due_at=due_at,
                review_started_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            )

    workflow_duration = (time.time() - workflow_start_time) * 1000
    logger.log_event(
        "claim_escalated",
        reasons=[e.reason],
        priority=e.priority,
        duration_ms=workflow_duration,
    )
    _record_crew_llm_usage(claim_id=claim_id, llm=llm, metrics=metrics)
    metrics.end_claim(claim_id, status="escalated")
    record_claim_outcome(
        claim_id, "escalated", (time.time() - workflow_start_time)
    )
    metrics.log_claim_summary(claim_id)

    summary = f"Escalated during {stage}: {e.reason}" if stage else f"Escalated mid-workflow: {e.reason}"
    return {
        "claim_id": claim_id,
        "claim_type": claim_type,
        "status": STATUS_NEEDS_REVIEW,
        "needs_review": True,
        "escalation_reasons": [e.reason],
        "priority": e.priority,
        "fraud_indicators": e.indicators,
        "router_output": raw_output,
        "workflow_output": saved_output,
        "workflow_run_id": workflow_run_id,
        "summary": summary,
    }


def _checkpoint_keys_to_invalidate(from_stage: str, checkpoints: dict[str, str]) -> list[str]:
    """Return checkpoint keys to delete when resuming from *from_stage* onwards."""
    try:
        idx = WORKFLOW_STAGES.index(from_stage)
    except ValueError:
        return []
    stages_to_drop = set(WORKFLOW_STAGES[idx:])
    return [
        key for key in checkpoints
        if (key.split(":")[0] if ":" in key else key) in stages_to_drop
    ]


@dataclass
class _WorkflowCtx:
    """Shared mutable context threaded through workflow stages."""

    claim_id: str
    claim_data: dict
    claim_data_with_id: dict
    inputs: dict
    similarity_score_for_escalation: float | None
    repo: ClaimRepository
    metrics: Any
    llm: Any
    workflow_run_id: str
    workflow_start_time: float
    actor_id: str
    checkpoints: dict[str, str] = field(default_factory=dict)

    claim_type: str = ""
    router_confidence: float = 0.0
    router_reasoning: str = ""
    raw_output: str = ""
    workflow_output: str = ""
    extracted_payout: float | None = None


def _stage_router(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the router classification stage.

    Returns an early-return response dict when the router escalates,
    otherwise populates ``ctx.claim_type``, ``ctx.router_confidence``,
    ``ctx.router_reasoning``, and ``ctx.raw_output`` and returns ``None``.
    """
    if "router" in ctx.checkpoints:
        try:
            router_cp = json.loads(ctx.checkpoints["router"])
            ctx.claim_type = router_cp["claim_type"]
            ctx.router_confidence = router_cp["router_confidence"]
            ctx.router_reasoning = router_cp["router_reasoning"]
            ctx.raw_output = router_cp["raw_output"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning(
                "Failed to restore router from checkpoint; discarding and re-running stage",
                extra={"claim_id": ctx.claim_id},
                exc_info=exc,
            )
            ctx.checkpoints.pop("router", None)
        else:
            logger.set_claim_type(ctx.claim_type)
            logger.info("Restored router from checkpoint", extra={"claim_id": ctx.claim_id})
            return None

    logger.log_event("router_started", step="classification")
    router_start = time.time()

    router_crew = create_router_crew(ctx.llm)
    result = _kickoff_with_retry(router_crew, ctx.inputs)

    router_latency = (time.time() - router_start) * 1000
    ctx.raw_output = str(
        getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    )
    ctx.claim_type, ctx.router_confidence, ctx.router_reasoning = _parse_router_output(
        result, ctx.raw_output
    )

    logger.set_claim_type(ctx.claim_type)
    logger.log_event(
        "router_completed",
        claim_type=ctx.claim_type,
        confidence=ctx.router_confidence,
        latency_ms=router_latency,
    )

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)

    router_config = get_router_config()
    confidence_threshold = router_config["confidence_threshold"]
    validation_enabled = router_config.get("validation_enabled", False)

    if ctx.router_confidence < confidence_threshold:
        if validation_enabled:
            try:
                val_json = validate_router_classification_impl(
                    ctx.claim_data_with_id,
                    ctx.claim_type,
                    ctx.router_confidence,
                    ctx.router_reasoning,
                    metrics=ctx.metrics,
                    claim_id=ctx.claim_id,
                )
                val_data = json.loads(val_json)
                val_claim_type = normalize_claim_type(val_data.get("claim_type", ctx.claim_type))
                val_confidence = max(0.0, min(1.0, float(val_data.get("confidence", 0))))
                val_agrees = val_data.get("validation_agrees", True)
                if val_confidence >= confidence_threshold:
                    if not val_agrees:
                        logger.log_event(
                            "router_reclassified",
                            original_claim_type=ctx.claim_type,
                            final_claim_type=val_claim_type,
                            validation_confidence=val_confidence,
                        )
                    ctx.claim_type = val_claim_type
                    ctx.router_confidence = val_confidence
                    ctx.router_reasoning = val_data.get("reasoning", ctx.router_reasoning)
                    logger.set_claim_type(ctx.claim_type)
                    try:
                        original_router_output = json.loads(ctx.raw_output)
                    except (TypeError, ValueError):
                        original_router_output = ctx.raw_output
                    ctx.raw_output = json.dumps({
                        "original_router_output": original_router_output,
                        "validation": val_data,
                    })
                    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
                else:
                    _escalate_low_router_confidence(
                        ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                        confidence_threshold, ctx.router_reasoning,
                        ctx.repo, logger, ctx.metrics, ctx.llm, ctx.workflow_start_time,
                        ctx.actor_id,
                    )
                    return _escalate_low_router_confidence_response(
                        ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                        confidence_threshold, router_reasoning=ctx.router_reasoning,
                    )
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning("Router validation parse failed: %s", e)
                _escalate_low_router_confidence(
                    ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                    confidence_threshold, ctx.router_reasoning,
                    ctx.repo, logger, ctx.metrics, ctx.llm, ctx.workflow_start_time,
                    ctx.actor_id,
                )
                return _escalate_low_router_confidence_response(
                    ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                    confidence_threshold, router_reasoning=ctx.router_reasoning,
                )
        else:
            _escalate_low_router_confidence(
                ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                confidence_threshold, ctx.router_reasoning,
                ctx.repo, logger, ctx.metrics, ctx.llm, ctx.workflow_start_time,
                ctx.actor_id,
            )
            return _escalate_low_router_confidence_response(
                ctx.claim_id, ctx.claim_type, ctx.raw_output, ctx.router_confidence,
                confidence_threshold, router_reasoning=ctx.router_reasoning,
            )

    ctx.repo.save_task_checkpoint(
        ctx.claim_id, ctx.workflow_run_id, "router",
        json.dumps({
            "claim_type": ctx.claim_type,
            "router_confidence": ctx.router_confidence,
            "router_reasoning": ctx.router_reasoning,
            "raw_output": ctx.raw_output,
        }),
    )
    return None


def _stage_escalation_check(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the pre-workflow escalation check.

    Returns an early-return response dict when the claim is escalated,
    otherwise returns ``None``.
    """
    if "escalation_check" in ctx.checkpoints:
        logger.info("Restored escalation_check from checkpoint", extra={"claim_id": ctx.claim_id})
        return None

    if ctx.claim_type != ClaimType.FRAUD.value:
        escalation_json = evaluate_escalation_impl(
            ctx.claim_data,
            ctx.raw_output,
            similarity_score=ctx.similarity_score_for_escalation,
            payout_amount=None,
            router_confidence=ctx.router_confidence,
        )
        escalation_result = json.loads(escalation_json)
        if escalation_result.get("needs_review"):
            reasons = escalation_result.get("escalation_reasons", [])
            priority = escalation_result.get("priority", "low")
            recommended_action = escalation_result.get("recommended_action", "")
            fraud_indicators = escalation_result.get("fraud_indicators", [])
            escalation_output = EscalationOutput(
                claim_id=ctx.claim_id,
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
            ctx.repo.save_workflow_result(ctx.claim_id, ctx.claim_type, ctx.raw_output, details)
            ctx.repo.update_claim_status(
                ctx.claim_id, STATUS_NEEDS_REVIEW, claim_type=ctx.claim_type,
                details=details, actor_id=ctx.actor_id,
            )
            hours = 24 if priority in ("critical", "high") else 48 if priority == "medium" else 72
            due_at = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
            ctx.repo.update_claim_review_metadata(
                ctx.claim_id, priority=priority, due_at=due_at,
                review_started_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
            )

            workflow_duration = (time.time() - ctx.workflow_start_time) * 1000
            logger.log_event(
                "claim_escalated", reasons=reasons, priority=priority,
                duration_ms=workflow_duration,
            )
            _record_crew_llm_usage(claim_id=ctx.claim_id, llm=ctx.llm, metrics=ctx.metrics)
            ctx.metrics.end_claim(ctx.claim_id, status="escalated")
            record_claim_outcome(
                ctx.claim_id, "escalated", (time.time() - ctx.workflow_start_time)
            )
            ctx.metrics.log_claim_summary(ctx.claim_id)

            return {
                **escalation_output.model_dump(),
                "claim_type": ctx.claim_type,
                "status": STATUS_NEEDS_REVIEW,
                "router_output": ctx.raw_output,
                "workflow_output": details,
                "workflow_run_id": ctx.workflow_run_id,
                "summary": f"Escalated for review: {', '.join(reasons)}",
            }

    ctx.repo.save_task_checkpoint(ctx.claim_id, ctx.workflow_run_id, "escalation_check", "{}")
    return None


def _stage_workflow_crew(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the primary workflow crew.

    Populates ``ctx.workflow_output`` and ``ctx.extracted_payout``.
    Returns an early-return response dict on mid-workflow escalation.
    """
    workflow_stage_key = f"workflow:{ctx.claim_type}"

    if workflow_stage_key in ctx.checkpoints:
        try:
            wf_cp = json.loads(ctx.checkpoints[workflow_stage_key])
            if not isinstance(wf_cp, dict):
                raise ValueError("workflow checkpoint is not a JSON object")
            ctx.workflow_output = wf_cp["workflow_output"]
            ctx.extracted_payout = wf_cp.get("extracted_payout")
            if ctx.extracted_payout is not None:
                ctx.claim_data_with_id["payout_amount"] = ctx.extracted_payout
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore %s from checkpoint; invalidating and re-running stage: %s",
                workflow_stage_key,
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop(workflow_stage_key, None)
        else:
            logger.info("Restored %s from checkpoint", workflow_stage_key, extra={"claim_id": ctx.claim_id})
            return None

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
    logger.log_event("crew_started", crew=ctx.claim_type)
    crew_start = time.time()

    if ctx.claim_type == ClaimType.NEW.value:
        crew = create_new_claim_crew(ctx.llm)
    elif ctx.claim_type == ClaimType.DUPLICATE.value:
        crew = create_duplicate_crew(ctx.llm)
    elif ctx.claim_type == ClaimType.FRAUD.value:
        crew = create_fraud_detection_crew(ctx.llm)
    elif ctx.claim_type == ClaimType.PARTIAL_LOSS.value:
        crew = create_partial_loss_crew(ctx.llm)
    else:
        crew = create_total_loss_crew(ctx.llm)

    crew_inputs = {
        "claim_data": json.dumps({**ctx.claim_data_with_id, "claim_type": ctx.claim_type}),
    }

    try:
        workflow_result = _kickoff_with_retry(crew, crew_inputs)
    except MidWorkflowEscalation as e:
        return _handle_mid_workflow_escalation(
            e,
            claim_id=ctx.claim_id,
            claim_type=ctx.claim_type,
            raw_output=ctx.raw_output,
            repo=ctx.repo,
            logger=logger,
            metrics=ctx.metrics,
            llm=ctx.llm,
            workflow_start_time=ctx.workflow_start_time,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
    crew_latency = (time.time() - crew_start) * 1000

    ctx.workflow_output = str(
        getattr(workflow_result, "raw", None)
        or getattr(workflow_result, "output", None)
        or str(workflow_result)
    )

    logger.log_event("crew_completed", crew=ctx.claim_type, latency_ms=crew_latency)

    ctx.extracted_payout = _extract_payout_from_workflow_result(workflow_result, ctx.claim_type)
    if ctx.extracted_payout is not None:
        ctx.claim_data_with_id["payout_amount"] = ctx.extracted_payout

    ctx.repo.save_task_checkpoint(
        ctx.claim_id, ctx.workflow_run_id, workflow_stage_key,
        json.dumps({
            "workflow_output": ctx.workflow_output,
            "extracted_payout": ctx.extracted_payout,
        }),
    )
    return None


def _stage_settlement(ctx: _WorkflowCtx) -> dict | None:
    """Run (or restore) the settlement crew when required by claim type.

    Returns an early-return response dict on mid-workflow escalation.
    Populates ``ctx.workflow_output`` with the combined final output.
    """
    if not _requires_settlement(ctx.claim_type):
        return None

    if "settlement" in ctx.checkpoints:
        try:
            stl_cp = json.loads(ctx.checkpoints["settlement"])
            if not isinstance(stl_cp, dict):
                raise ValueError("settlement checkpoint is not a JSON object")
            settlement_output = stl_cp["settlement_output"]
            ctx.workflow_output = _combine_workflow_outputs(ctx.workflow_output, settlement_output)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "Failed to restore settlement from checkpoint; invalidating and re-running stage: %s",
                exc,
                extra={"claim_id": ctx.claim_id},
            )
            ctx.checkpoints.pop("settlement", None)
        else:
            logger.info("Restored settlement from checkpoint", extra={"claim_id": ctx.claim_id})
            return None

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
    logger.log_event("crew_started", crew="settlement")
    settlement_start = time.time()

    settlement_crew = create_settlement_crew(ctx.llm, claim_type=ctx.claim_type)
    settlement_inputs = {
        "claim_data": json.dumps({**ctx.claim_data_with_id, "claim_type": ctx.claim_type}),
        "workflow_output": ctx.workflow_output,
    }

    try:
        settlement_result = _kickoff_with_retry(settlement_crew, settlement_inputs)
    except MidWorkflowEscalation as e:
        return _handle_mid_workflow_escalation(
            e,
            claim_id=ctx.claim_id,
            claim_type=ctx.claim_type,
            raw_output=ctx.raw_output,
            repo=ctx.repo,
            logger=logger,
            metrics=ctx.metrics,
            llm=ctx.llm,
            workflow_start_time=ctx.workflow_start_time,
            prior_workflow_output=ctx.workflow_output,
            actor_id=ctx.actor_id,
            stage="settlement",
            payout_amount=ctx.extracted_payout,
            workflow_run_id=ctx.workflow_run_id,
        )

    _check_token_budget(ctx.claim_id, ctx.metrics, ctx.llm)
    settlement_latency = (time.time() - settlement_start) * 1000
    settlement_output = str(
        getattr(settlement_result, "raw", None)
        or getattr(settlement_result, "output", None)
        or str(settlement_result)
    )
    logger.log_event("crew_completed", crew="settlement", latency_ms=settlement_latency)
    ctx.workflow_output = _combine_workflow_outputs(ctx.workflow_output, settlement_output)

    ctx.repo.save_task_checkpoint(
        ctx.claim_id, ctx.workflow_run_id, "settlement",
        json.dumps({"settlement_output": settlement_output}),
    )
    return None


def run_claim_workflow(
    claim_data: dict,
    llm=None,
    existing_claim_id: str | None = None,
    *,
    actor_id: str | None = None,
    resume_run_id: str | None = None,
    from_stage: str | None = None,
) -> dict:
    """
    Run the full claim workflow: classify with router crew, then run the appropriate workflow crew.
    Persists claim to SQLite, logs state changes, and saves workflow result.

    Supports resumable execution via checkpoints.  When *resume_run_id* is
    provided, completed stages are skipped using cached outputs.  When
    *from_stage* is also given, checkpoints at and after that stage are
    invalidated so execution restarts from that point.

    Args:
        claim_data: dict with policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
                   incident_date, incident_description, damage_description, estimated_damage (optional).
        llm: Optional LLM instance. If None, uses default from config.
        existing_claim_id: if set, re-run workflow for this claim (no new claim created).
        actor_id: Actor to record in audit log entries.
        resume_run_id: Reuse checkpoints from this workflow run (resume mode).
        from_stage: When resuming, invalidate checkpoints at and after this stage
            and re-execute from here.  One of ``WORKFLOW_STAGES``.

    Returns:
        dict with claim_id, claim_type, status, summary, workflow_output, and
        workflow_run_id (for future resume).
    """
    workflow_start_time = time.time()
    _actor = actor_id if actor_id is not None else ACTOR_WORKFLOW

    llm = llm or get_llm()
    claim_input, claim_data = _normalize_claim_data(claim_data)
    repo = ClaimRepository()
    metrics = get_metrics()

    # Create or retrieve claim
    if existing_claim_id:
        claim_id = existing_claim_id
        if repo.get_claim(claim_id) is None:
            raise ValueError(f"Claim not found: {claim_id}")
        logger.info("Reprocessing existing claim", extra={"claim_id": claim_id})
    else:
        claim_id = repo.create_claim(claim_input, actor_id=_actor)
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
        vin=claim_data.get("vin"),
    ):
        # Both new and reprocessed claims set to PROCESSING for consistent workflow tracking
        repo.update_claim_status(claim_id, STATUS_PROCESSING, actor_id=_actor)
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
            # Checkpoint initialization for resumable workflows
            if from_stage and not resume_run_id:
                logger.warning(
                    "from_stage=%s ignored because resume_run_id is not set",
                    from_stage,
                    extra={"claim_id": claim_id},
                )
                from_stage = None

            workflow_run_id = resume_run_id or uuid.uuid4().hex
            checkpoints: dict[str, str] = {}
            if resume_run_id:
                checkpoints = repo.get_task_checkpoints(claim_id, workflow_run_id)
                if from_stage:
                    keys_to_drop = _checkpoint_keys_to_invalidate(from_stage, checkpoints)
                    if keys_to_drop:
                        repo.delete_task_checkpoints(claim_id, workflow_run_id, keys_to_drop)
                        for k in keys_to_drop:
                            checkpoints.pop(k, None)
                logger.info(
                    "Resuming workflow run %s with %d checkpoint(s)",
                    workflow_run_id,
                    len(checkpoints),
                    extra={"claim_id": claim_id},
                )

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
            similarity_score_for_escalation = None
            if existing_claims:
                from claim_agent.tools.logic import compute_similarity_score_impl
                current_incident = claim_data.get("incident_description", "") or ""
                current_damage = claim_data.get("damage_description", "") or ""
                current_combined = f"{current_incident} {current_damage}"
                current_damage_tags = _extract_damage_tags(current_combined)
                
                enriched_claims = []
                for c in existing_claims[:5]:
                    existing_incident = c.get("incident_description", "") or ""
                    existing_damage = c.get("damage_description", "") or ""
                    existing_combined = f"{existing_incident} {existing_damage}"
                    existing_damage_tags = _extract_damage_tags(existing_combined)
                    damage_type_match = _damage_tags_overlap(current_damage_tags, existing_damage_tags)
                    
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
                        "damage_description": existing_damage[:200],
                        "damage_tags": sorted(existing_damage_tags),
                        "damage_type_match": damage_type_match,
                        "days_difference": c.get("days_difference"),
                        "description_similarity_score": similarity_score,
                    })
                    if similarity_score_for_escalation is None or similarity_score > similarity_score_for_escalation:
                        similarity_score_for_escalation = similarity_score
                
                claim_data_with_id["existing_claims_for_vin"] = enriched_claims
                claim_data_with_id["damage_tags"] = sorted(current_damage_tags)
                # Deterministic duplicate: if any existing claim meets thresholds, set definitive_duplicate
                is_high_value = claim_data_with_id.get("high_value_claim", False)
                sim_threshold = 60 if is_high_value else 40
                definitive_duplicate = any(
                    (e.get("description_similarity_score") or 0) >= sim_threshold
                    and e.get("days_difference", 999) <= 3
                    and e.get("damage_type_match")
                    for e in enriched_claims
                )
                claim_data_with_id["definitive_duplicate"] = definitive_duplicate
            else:
                similarity_score_for_escalation = None
                claim_data_with_id["definitive_duplicate"] = False
            inputs = {"claim_data": json.dumps(claim_data_with_id) if isinstance(claim_data_with_id, dict) else claim_data_with_id}
            claim_data_str = inputs["claim_data"] if isinstance(inputs["claim_data"], str) else json.dumps(inputs["claim_data"])
            logger.debug(
                "router_input_size claim_id=%s payload_chars=%s existing_claims_count=%s",
                claim_id,
                len(claim_data_str),
                len(claim_data_with_id.get("existing_claims_for_vin") or []),
            )

            ctx = _WorkflowCtx(
                claim_id=claim_id,
                claim_data=claim_data,
                claim_data_with_id=claim_data_with_id,
                inputs=inputs,
                similarity_score_for_escalation=similarity_score_for_escalation,
                repo=repo,
                metrics=metrics,
                llm=llm,
                workflow_run_id=workflow_run_id,
                workflow_start_time=workflow_start_time,
                actor_id=_actor,
                checkpoints=checkpoints,
            )

            for stage_fn in (_stage_router, _stage_escalation_check, _stage_workflow_crew, _stage_settlement):
                early_return = stage_fn(ctx)
                if early_return is not None:
                    return early_return

            final_status = _final_status(ctx.claim_type)
            repo.save_workflow_result(claim_id, ctx.claim_type, ctx.raw_output, ctx.workflow_output)
            repo.update_claim_status(
                claim_id,
                final_status,
                details=ctx.workflow_output[:500] if len(ctx.workflow_output) > 500 else ctx.workflow_output,
                claim_type=ctx.claim_type,
                payout_amount=ctx.extracted_payout,
                actor_id=_actor,
            )

            workflow_duration = (time.time() - workflow_start_time) * 1000
            logger.log_event(
                "workflow_completed",
                status=final_status,
                duration_ms=workflow_duration,
            )

            _record_crew_llm_usage(claim_id=claim_id, llm=llm, metrics=metrics)

            metrics.end_claim(claim_id, status=final_status)
            record_claim_outcome(
                claim_id, final_status, (time.time() - workflow_start_time)
            )
            metrics.log_claim_summary(claim_id)

            return {
                "claim_id": claim_id,
                "claim_type": ctx.claim_type,
                "status": final_status,
                "router_output": ctx.raw_output,
                "workflow_output": ctx.workflow_output,
                "workflow_run_id": workflow_run_id,
                "summary": ctx.workflow_output[:500] + "..." if len(ctx.workflow_output) > 500 else ctx.workflow_output,
            }
        except Exception as e:
            details = str(e)
            if len(details) > 500:
                details = details[:500] + "..."
            repo.update_claim_status(claim_id, STATUS_FAILED, details=details, actor_id=_actor)

            workflow_duration = (time.time() - workflow_start_time) * 1000
            logger.log_event(
                "workflow_failed",
                error=details,
                duration_ms=workflow_duration,
                level=logging.ERROR,
            )

            # Record CrewAI LLM usage before ending metrics tracking
            _record_crew_llm_usage(claim_id=claim_id, llm=llm, metrics=metrics)

            # End metrics tracking with error status
            metrics.end_claim(claim_id, status="error")
            record_claim_outcome(
                claim_id, "error", (time.time() - workflow_start_time)
            )
            metrics.log_claim_summary(claim_id)

            raise
        finally:
            with _callbacks_lock:
                current_callbacks = list(getattr(litellm, "callbacks", None) or [])
                litellm.callbacks = [cb for cb in current_callbacks if cb is not litellm_callback]
