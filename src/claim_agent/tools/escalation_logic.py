"""Escalation (HITL) logic: evaluate escalation, detect fraud indicators, router helpers."""

import json
import logging
import os
from datetime import date, datetime, timedelta
from typing import Any

from claim_agent.config.settings import get_escalation_config
from claim_agent.db.audit_events import ACTOR_WORKFLOW, AUDIT_EVENT_ESCALATION
from claim_agent.db.constants import STATUS_NEEDS_REVIEW
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimType
from claim_agent.tools.valuation_logic import fetch_vehicle_value_impl

try:
    import litellm
except ImportError:
    litellm = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

KNOWN_FRAUD_PATTERNS = {
    "staged_accident_keywords": [
        "multiple occupants",
        "all passengers injured",
        "witnesses left",
        "witness left",
        "no witnesses",
        "brake checked",
        "sudden stop",
    ],
    "suspicious_claim_keywords": [
        "staged",
        "inflated",
        "pre-existing",
        "inconsistent",
        "misrepresentation",
        "material misrepresentation",
        "exaggerated",
        "fabricated",
        "prior claims",
        "suspicious damage",
    ],
    "timing_red_flags": [
        "new policy",
        "policy just started",
        "recently insured",
        "just purchased",
        "first day",
    ],
    "damage_fraud_keywords": [
        "total destruction",
        "complete loss",
        "beyond repair",
        "catastrophic",
        "all components damaged",
    ],
}


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
{{"claim_type": "new"|"duplicate"|"total_loss"|"fraud"|"partial_loss", "confidence": 0.0-1.0, "reasoning": "brief explanation"}}"""

    try:
        model = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini")
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
    repo: ClaimRepository | None = None,
) -> str:
    """Check claim for fraud indicators. Returns JSON list of indicator strings."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return json.dumps(indicators)

    incident = (claim_data.get("incident_description") or "").strip().lower()
    damage = (claim_data.get("damage_description") or "").strip().lower()
    vin = (claim_data.get("vin") or "").strip()
    incident_date_raw = claim_data.get("incident_date")
    if isinstance(incident_date_raw, datetime):
        incident_date = incident_date_raw.strftime("%Y-%m-%d")
    elif isinstance(incident_date_raw, date):
        incident_date = incident_date_raw.isoformat()
    elif isinstance(incident_date_raw, str):
        incident_date = incident_date_raw.strip()
    else:
        incident_date = ""
    estimated_damage = claim_data.get("estimated_damage")
    if isinstance(estimated_damage, str):
        try:
            estimated_damage = float(estimated_damage)
        except ValueError:
            estimated_damage = None

    fraud_keywords = (
        KNOWN_FRAUD_PATTERNS["staged_accident_keywords"]
        + KNOWN_FRAUD_PATTERNS["suspicious_claim_keywords"]
    )
    combined = f"{incident} {damage}"
    for kw in fraud_keywords:
        if kw in combined:
            indicators.append(kw.replace(" ", "_"))

    if vin and incident_date:
        try:
            _repo = repo or ClaimRepository()
            dt_obj = datetime.strptime(incident_date, "%Y-%m-%d")
            start = (dt_obj - timedelta(days=get_escalation_config()["vin_claims_days"])).strftime("%Y-%m-%d")
            end = (dt_obj + timedelta(days=1)).strftime("%Y-%m-%d")
            matches = _repo.search_claims(vin=vin, incident_date=None)
            same_vin = [m for m in matches if m.get("vin") == vin and m.get("incident_date") != incident_date]
            same_vin_in_window = [
                m for m in same_vin
                if m.get("incident_date") is not None and start <= m.get("incident_date") <= end
            ]
            if len(same_vin_in_window) >= 1:
                indicators.append("multiple_claims_same_vin")
        except (ValueError, OSError):
            pass

    if estimated_damage is not None and isinstance(estimated_damage, (int, float)) and estimated_damage > 0:
        year = claim_data.get("vehicle_year")
        make = claim_data.get("make") or claim_data.get("vehicle_make") or ""
        model = claim_data.get("model") or claim_data.get("vehicle_model") or ""
        if year and make and model:
            val_res = fetch_vehicle_value_impl(vin or "", year, make, model)
            try:
                val_data = json.loads(val_res)
                vehicle_value = val_data.get("value")
                if isinstance(vehicle_value, (int, float)) and vehicle_value > 0:
                    if estimated_damage >= get_escalation_config()["fraud_damage_vs_value_ratio"] * vehicle_value:
                        indicators.append("damage_near_or_above_vehicle_value")
            except (json.JSONDecodeError, TypeError):
                pass

    overlap_threshold = get_escalation_config()["description_overlap_threshold"]
    if incident and damage:
        words_i = set(incident.split())
        words_d = set(damage.split())
        if words_i and words_d:
            overlap = len(words_i & words_d) / len(words_i | words_d) if (words_i | words_d) else 0
            if overlap < overlap_threshold:
                indicators.append("incident_damage_description_mismatch")

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
    repo: ClaimRepository | None = None,
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

    fraud_json = detect_fraud_indicators_impl(claim_data or {}, repo=repo)
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
    repo: ClaimRepository | None = None,
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

    _repo = repo or ClaimRepository()
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
    due_at = (datetime.utcnow() + timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    _repo.update_claim_review_metadata(
        claim_id,
        priority=priority,
        due_at=due_at,
        review_started_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    )

    _repo.insert_audit_entry(
        claim_id,
        AUDIT_EVENT_ESCALATION,
        new_status=STATUS_NEEDS_REVIEW,
        details=f"Mid-workflow escalation: {reason}",
        actor_id=actor_id,
        after_state=details,
    )
