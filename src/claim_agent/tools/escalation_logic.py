"""Escalation (HITL) logic: evaluate escalation, detect fraud indicators, router helpers."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from claim_agent.config.llm import get_model_name
from claim_agent.config.settings import get_escalation_config
from claim_agent.db.audit_events import ACTOR_WORKFLOW, AUDIT_EVENT_ESCALATION
from claim_agent.db.constants import STATUS_NEEDS_REVIEW
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimType
from claim_agent.tools.fraud_detectors import run_fraud_detectors

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


def normalize_claim_type(value: str) -> str:
    """Normalize claim_type string to canonical value."""
    v = (value or "").strip().lower().replace(" ", "_")
    if v == "total_loss":
        return ClaimType.TOTAL_LOSS.value
    if v == "partial_loss":
        return ClaimType.PARTIAL_LOSS.value
    if v == "new":
        return ClaimType.NEW.value
    if v == "duplicate":
        return ClaimType.DUPLICATE.value
    if v == "fraud":
        return ClaimType.FRAUD.value
    if v == "bodily_injury":
        return ClaimType.BODILY_INJURY.value
    if v == "reopened":
        return ClaimType.REOPENED.value
    return ClaimType.NEW.value


def _extract_json_from_text(text: str) -> dict | None:
    """Extract JSON object from LLM output text."""
    text = text.strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass
    if "```json" in text:
        try:
            extracted = text.split("```json")[1].split("```")[0].strip()
            parsed = json.loads(extracted)
            return parsed if isinstance(parsed, dict) else None
        except (IndexError, json.JSONDecodeError):
            pass
    elif "```" in text:
        try:
            extracted = text.split("```")[1].split("```")[0].strip()
            parsed = json.loads(extracted)
            return parsed if isinstance(parsed, dict) else None
        except (IndexError, json.JSONDecodeError):
            pass
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, c in enumerate(text[start:], start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def validate_router_classification_impl(
    claim_data: dict[str, Any],
    original_claim_type: str,
    original_confidence: float,
    original_reasoning: str,
    *,
    metrics: Any = None,
    claim_id: str | None = None,
) -> str:
    """Optional validation: second LLM call to confirm or correct router classification."""
    if litellm is None:
        return json.dumps({
            "claim_type": original_claim_type,
            "confidence": original_confidence,
            "reasoning": "Validation skipped: litellm not available",
            "validation_agrees": True,
        })

    claim_str = json.dumps(claim_data, default=str)[:2000]
    prompt = f"""A claim was classified as "{original_claim_type}" with confidence {original_confidence:.2f}. Reasoning: {original_reasoning}

Claim data (excerpt): {claim_str}

Independently verify the classification. Return JSON only:
{{"claim_type": "new"|"duplicate"|"total_loss"|"fraud"|"partial_loss"|"bodily_injury", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}"""

    try:
        model = get_model_name()
        resp = litellm.completion(model=model, messages=[{"role": "user", "content": prompt}])
        text = (resp.choices[0].message.content or "").strip()
        parsed = _extract_json_from_text(text)
        if parsed:
            v_type = normalize_claim_type(parsed.get("claim_type", "") or original_claim_type)
            v_conf = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
            v_reason = str(parsed.get("reasoning", "") or "").strip()
            orig_normalized = normalize_claim_type(original_claim_type)
            agrees = v_type == orig_normalized
            result = json.dumps({
                "claim_type": v_type,
                "confidence": v_conf,
                "reasoning": v_reason,
                "validation_agrees": agrees,
            })
            if metrics is not None and claim_id:
                usage = getattr(resp, "usage", None)
                prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
                completion_tokens = getattr(usage, "completion_tokens", 0) or 0
                model_name = getattr(resp, "model", None) or str(model)
                metrics.record_llm_call(
                    claim_id=claim_id,
                    model=model_name,
                    input_tokens=int(prompt_tokens),
                    output_tokens=int(completion_tokens),
                )
            return result
    except Exception as e:
        logger.warning("Router validation failed: %s", e, exc_info=True)
    return json.dumps({
        "claim_type": original_claim_type,
        "confidence": original_confidence,
        "reasoning": "Validation failed, using original",
        "validation_agrees": False,
    })


def _parse_router_confidence(router_output: str) -> float:
    """Derive routing confidence from router output language, in the range 0.3-1.0."""
    if not router_output or not isinstance(router_output, str):
        return 0.5
    low_confidence_patterns = ["possibly", "might be", "unclear", "unsure", "could be", "uncertain"]
    confidence = 1.0
    text = router_output.strip().lower()
    decrement = get_escalation_config()["confidence_decrement_per_pattern"]
    for pattern in low_confidence_patterns:
        if pattern in text:
            confidence -= decrement
    return max(0.3, min(1.0, confidence))


def detect_fraud_indicators_impl(
    claim_data: dict[str, Any],
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Check claim for fraud indicators via pluggable detectors. Returns JSON list of indicator strings."""
    indicators = run_fraud_detectors(claim_data or {}, ctx=ctx)
    return json.dumps(indicators)


def compute_escalation_priority_impl(reasons: list[str], fraud_indicators: list[str]) -> str:
    """Compute escalation priority from reasons and fraud indicators."""
    reason_count = len(reasons) if reasons else 0
    fraud_count = len(fraud_indicators) if fraud_indicators else 0
    has_fraud = "fraud_suspected" in (reasons or []) or fraud_count > 0

    if fraud_count >= 2 or (has_fraud and reason_count >= 2):
        priority = "critical"
    elif reason_count >= 3 or has_fraud:
        priority = "high"
    elif reason_count == 2:
        priority = "medium"
    elif reason_count == 1:
        priority = "low"
    else:
        priority = "low"
    return json.dumps({"priority": priority})


def evaluate_escalation_impl(
    claim_data: dict[str, Any],
    router_output: str,
    similarity_score: float | None = None,
    payout_amount: float | None = None,
    *,
    router_confidence: float | None = None,
    ctx: ClaimContext | None = None,
) -> str:
    """Evaluate claim for escalation."""
    reasons: list[str] = []
    esc_config = get_escalation_config()
    conf_threshold = esc_config["confidence_threshold"]
    high_value_threshold = esc_config["high_value_threshold"]
    low_sim, high_sim = esc_config["similarity_ambiguous_range"]

    if router_confidence is not None:
        confidence = max(0.0, min(1.0, float(router_confidence)))
    else:
        confidence = _parse_router_confidence(router_output or "")
    if confidence < conf_threshold:
        reasons.append("low_confidence")

    estimated = claim_data.get("estimated_damage") if isinstance(claim_data, dict) else None
    if isinstance(estimated, str):
        try:
            estimated = float(estimated)
        except ValueError:
            estimated = None
    value_to_check = payout_amount if payout_amount is not None else estimated
    if isinstance(value_to_check, (int, float)) and value_to_check >= high_value_threshold:
        reasons.append("high_value")

    if similarity_score is not None and low_sim <= similarity_score <= high_sim:
        reasons.append("ambiguous_similarity")

    fraud_json = detect_fraud_indicators_impl(claim_data or {}, ctx=ctx)
    try:
        fraud_indicators = json.loads(fraud_json)
    except (json.JSONDecodeError, TypeError):
        fraud_indicators = []
    if fraud_indicators:
        reasons.append("fraud_suspected")

    priority_json = compute_escalation_priority_impl(reasons, fraud_indicators)
    try:
        priority = json.loads(priority_json).get("priority", "low")
    except (json.JSONDecodeError, TypeError):
        priority = "low"

    needs_review = len(reasons) > 0
    if needs_review:
        recommended = "Review claim manually. "
        if "fraud_suspected" in reasons:
            recommended += "Refer to SIU if fraud indicators are confirmed. "
        if "high_value" in reasons:
            recommended += "Verify valuation and damage estimate. "
        if "low_confidence" in reasons:
            recommended += "Confirm routing classification. "
        if "ambiguous_similarity" in reasons:
            recommended += "Confirm duplicate vs new claim."
    else:
        recommended = "No escalation needed."

    return json.dumps({
        "needs_review": needs_review,
        "escalation_reasons": reasons,
        "priority": priority,
        "fraud_indicators": fraud_indicators,
        "recommended_action": recommended.strip(),
    })


def escalate_claim_impl(
    claim_id: str,
    reason: str,
    indicators: list[str],
    priority: str,
    *,
    claim_type: str | None = None,
    actor_id: str = ACTOR_WORKFLOW,
    ctx: ClaimContext | None = None,
) -> None:
    """Persist mid-workflow escalation: set status to needs_review, save details, audit log."""
    if not claim_id or not isinstance(claim_id, str) or not claim_id.strip():
        raise ValueError("claim_id is required for escalate_claim")
    claim_id = claim_id.strip()
    if not reason or not isinstance(reason, str) or not reason.strip():
        raise ValueError("reason is required for escalate_claim")
    reason = reason.strip()
    if indicators is None:
        indicators = []
    elif isinstance(indicators, (list, tuple)):
        indicators = [str(x) for x in indicators if x is not None]
    else:
        raise ValueError("indicators must be a list or tuple of strings for escalate_claim")
    valid_priorities = ("low", "medium", "high", "critical")
    priority = (priority or "medium").strip().lower()
    if priority not in valid_priorities:
        priority = "medium"

    _repo = ctx.repo if ctx else ClaimRepository()
    details = json.dumps({
        "escalation": True,
        "mid_workflow": True,
        "reason": reason,
        "indicators": indicators,
        "priority": priority,
    })

    _repo.update_claim_status(
        claim_id,
        STATUS_NEEDS_REVIEW,
        details=details,
        claim_type=claim_type,
        actor_id=actor_id,
    )

    hours = 24 if priority in ("critical", "high") else 48 if priority == "medium" else 72
    due_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    _repo.update_claim_review_metadata(
        claim_id,
        priority=priority,
        due_at=due_at,
        review_started_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    )

    _repo.insert_audit_entry(
        claim_id,
        AUDIT_EVENT_ESCALATION,
        new_status=STATUS_NEEDS_REVIEW,
        details=f"Mid-workflow escalation: {reason}",
        actor_id=actor_id,
        after_state=details,
    )
