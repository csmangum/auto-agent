"""Shared logic for claim tools (used by both CrewAI tools and MCP server)."""

import json
import logging
import uuid
from datetime import datetime, timedelta

from claim_agent.tools.data_loader import load_mock_db, load_california_compliance
from claim_agent.db.repository import ClaimRepository

# Set up logger
logger = logging.getLogger(__name__)

# Vehicle valuation defaults (mock KBB)
DEFAULT_BASE_VALUE = 12000
DEPRECIATION_PER_YEAR = 500
MIN_VEHICLE_VALUE = 2000

# Payout calculation defaults
DEFAULT_DEDUCTIBLE = 500
MIN_PAYOUT_VEHICLE_VALUE = 100  # Minimum vehicle value for payout calculation
# Escalation thresholds (HITL)
ESCALATION_CONFIG = {
    "confidence_threshold": 0.7,
    "high_value_threshold": 10000.0,
    "similarity_ambiguous_range": (50, 80),
    "fraud_damage_vs_value_ratio": 0.9,
    "vin_claims_days": 90,
    "confidence_decrement_per_pattern": 0.15,
    "description_overlap_threshold": 0.1,
}


def query_policy_db_impl(policy_number: str) -> str:
    if not policy_number or not isinstance(policy_number, str):
        return json.dumps({"valid": False, "message": "Invalid policy number"})
    policy_number = policy_number.strip()
    if not policy_number:
        return json.dumps({"valid": False, "message": "Empty policy number"})
    db = load_mock_db()
    policies = db.get("policies", {})
    if policy_number in policies:
        p = policies[policy_number]
        status = p.get("status", "active")
        is_active = isinstance(status, str) and status.lower() == "active"
        if is_active:
            return json.dumps({
                "valid": True,
                "coverage": p.get("coverage", "comprehensive"),
                "deductible": p.get("deductible", 500),
                "status": status,
            })
        return json.dumps({
            "valid": False,
            "status": status,
            "message": "Policy not found or inactive",
        })
    return json.dumps({"valid": False, "message": "Policy not found or inactive"})


def search_claims_db_impl(vin: str, incident_date: str) -> str:
    if not vin or not isinstance(vin, str) or not vin.strip():
        return json.dumps([])
    if not incident_date or not isinstance(incident_date, str) or not incident_date.strip():
        return json.dumps([])
    repo = ClaimRepository()
    matches = repo.search_claims(vin=vin.strip(), incident_date=incident_date.strip())
    # Return shape expected by tools: claim_id, vin, incident_date, incident_description
    out = [
        {
            "claim_id": c.get("id"),
            "vin": c.get("vin"),
            "incident_date": c.get("incident_date"),
            "incident_description": c.get("incident_description", ""),
        }
        for c in matches
    ]
    return json.dumps(out)


def compute_similarity_impl(description_a: str, description_b: str) -> str:
    a = description_a.lower().strip()
    b = description_b.lower().strip()
    if not a or not b:
        return json.dumps({"similarity_score": 0.0, "is_duplicate": False})
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return json.dumps({"similarity_score": 0.0, "is_duplicate": False})
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    score = (intersection / union) * 100.0
    return json.dumps({"similarity_score": round(score, 2), "is_duplicate": score > 80.0})


def fetch_vehicle_value_impl(vin: str, year: int, make: str, model: str) -> str:
    vin = vin.strip() if isinstance(vin, str) else ""
    make = make.strip() if isinstance(make, str) else ""
    model = model.strip() if isinstance(model, str) else ""
    year_int = int(year) if isinstance(year, (int, float)) and year > 0 else 2020
    db = load_mock_db()
    key = vin or f"{year_int}_{make}_{model}"
    values = db.get("vehicle_values", {})
    if key in values:
        v = values[key]
        return json.dumps({
            "value": v.get("value", 15000),
            "condition": v.get("condition", "good"),
            "source": "mock_kbb",
        })
    current_year = datetime.now().year
    default_value = max(
        MIN_VEHICLE_VALUE,
        DEFAULT_BASE_VALUE + (current_year - year_int) * -DEPRECIATION_PER_YEAR,
    )
    return json.dumps({
        "value": default_value,
        "condition": "good",
        "source": "mock_kbb_estimated",
    })


def evaluate_damage_impl(damage_description: str, estimated_repair_cost: float | None) -> str:
    if not damage_description or not isinstance(damage_description, str):
        return json.dumps({
            "severity": "unknown",
            "estimated_repair_cost": estimated_repair_cost if estimated_repair_cost is not None else 0.0,
            "total_loss_candidate": False,
        })
    desc_lower = damage_description.strip().lower()
    if not desc_lower:
        return json.dumps({
            "severity": "unknown",
            "estimated_repair_cost": estimated_repair_cost if estimated_repair_cost is not None else 0.0,
            "total_loss_candidate": False,
        })
    total_loss_keywords = ["totaled", "total loss", "destroyed", "flood", "fire", "frame"]
    is_total_loss_candidate = any(k in desc_lower for k in total_loss_keywords)
    cost = estimated_repair_cost if estimated_repair_cost is not None else 0.0
    return json.dumps({
        "severity": "high" if is_total_loss_candidate else "medium",
        "estimated_repair_cost": cost,
        "total_loss_candidate": is_total_loss_candidate,
    })


def generate_report_impl(
    claim_id: str,
    claim_type: str,
    status: str,
    summary: str,
    payout_amount: float | None = None,
) -> str:
    report = {
        "report_id": str(uuid.uuid4()),
        "claim_id": claim_id,
        "claim_type": claim_type,
        "status": status,
        "summary": summary,
        "payout_amount": payout_amount,
    }
    return json.dumps(report)


def generate_claim_id_impl(prefix: str = "CLM") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _json_contains_query(obj: object, query: str) -> bool:
    """Return True if any string value in obj (recursively) contains query (case-insensitive)."""
    q = query.strip().lower()
    if not q:
        return False
    if isinstance(obj, str):
        return q in obj.lower()
    if isinstance(obj, dict):
        return any(_json_contains_query(v, query) for v in obj.values())
    if isinstance(obj, list):
        return any(_json_contains_query(v, query) for v in obj)
    return False


def _gather_matches(data: dict, query: str, section_key: str, matches: list) -> None:
    """Recursively gather dicts/lists that contain the query; treat known list keys as item boundaries."""
    if not _json_contains_query(data, query):
        return
    # Known keys whose values are lists of provisions/deadlines/disclosures etc.
    list_keys = {"provisions", "deadlines", "disclosures", "prohibited_practices", "key_provisions", "requirements", "limitations", "scenarios", "remedies", "penalties", "consumer_services", "tolling_provisions", "proof_methods"}
    for key, value in data.items():
        if key == "metadata":
            continue
        if key in list_keys and isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict) and _json_contains_query(item, query):
                    matches.append({"section": section_key, "subsection": key, "item": item})
        elif isinstance(value, dict):
            _gather_matches(value, query, section_key or key, matches)
        elif isinstance(value, list) and value and isinstance(value[0], dict):
            for item in value:
                if _json_contains_query(item, query):
                    matches.append({"section": section_key, "item": item})


def search_california_compliance_impl(query: str) -> str:
    """Search California auto compliance data by keyword. Empty query returns section summary."""
    data = load_california_compliance()
    if not data:
        return json.dumps({"error": "California compliance data not available", "matches": []})
    query = (query or "").strip()
    if not query:
        summary = {
            "metadata": data.get("metadata", {}),
            "sections": [k for k in data.keys() if k != "metadata"],
        }
        return json.dumps(summary)
    matches: list = []
    for section_key, section_value in data.items():
        if section_key == "metadata":
            continue
        if isinstance(section_value, dict):
            _gather_matches(section_value, query, section_key, matches)
        elif _json_contains_query(section_value, query):
            matches.append({"section": section_key, "content": section_value})
    return json.dumps({"query": query, "match_count": len(matches), "matches": matches})


def calculate_payout_impl(vehicle_value: float, policy_number: str) -> str:
    """Calculate total loss payout by subtracting deductible from vehicle value.
    Args:
        vehicle_value: Current market value of the vehicle.
        policy_number: Policy number to look up deductible.
    Returns:
        JSON string with payout_amount (float), vehicle_value (float), deductible (float), and calculation (str).
    """
    if not isinstance(vehicle_value, (int, float)) or vehicle_value < MIN_PAYOUT_VEHICLE_VALUE:
        return json.dumps({
            "error": f"Invalid vehicle value (minimum: ${MIN_PAYOUT_VEHICLE_VALUE})",
            "payout_amount": 0.0,
            "vehicle_value": vehicle_value,
            "deductible": 0,
            "calculation": f"Error: Vehicle value must be at least ${MIN_PAYOUT_VEHICLE_VALUE}"
        })
    
    # Round vehicle value for currency consistency
    vehicle_value = round(vehicle_value, 2)
    
    # Query policy to get deductible
    policy_result = query_policy_db_impl(policy_number)
    try:
        policy_data = json.loads(policy_result)
        if not policy_data.get("valid", False):
            return json.dumps({
                "error": "Invalid or inactive policy",
                "payout_amount": 0.0,
                "vehicle_value": vehicle_value,
                "deductible": 0,
                "calculation": "Error: Policy not found or inactive"
            })
        deductible = policy_data.get("deductible", DEFAULT_DEDUCTIBLE)
    except (json.JSONDecodeError, KeyError) as e:
        # Unexpected error in policy lookup - log for monitoring
        logger.error(f"Unexpected policy lookup error for policy {policy_number}: {e}")
        return json.dumps({
            "error": f"Policy lookup error: {str(e)}",
            "payout_amount": 0.0,
            "vehicle_value": vehicle_value,
            "deductible": 0,
            "calculation": "Error: Unable to retrieve policy information"
        })
    
    # Calculate payout
    payout_amount = max(0.0, vehicle_value - deductible)
    
    result = {
        "payout_amount": round(payout_amount, 2),
        "vehicle_value": vehicle_value,
        "deductible": deductible,
        "calculation": f"${vehicle_value:,.2f} (vehicle value) - ${deductible:,.2f} (deductible) = ${payout_amount:,.2f}"
    }
    
    return json.dumps(result)


# --- Escalation (HITL) ---


def _parse_router_confidence(router_output: str) -> float:
    """Derive routing confidence from router output language, in the range 0.3-1.0."""
    if not router_output or not isinstance(router_output, str):
        return 0.5
    low_confidence_patterns = ["possibly", "might be", "unclear", "unsure", "could be", "uncertain"]
    confidence = 1.0
    text = router_output.strip().lower()
    decrement = ESCALATION_CONFIG["confidence_decrement_per_pattern"]
    for pattern in low_confidence_patterns:
        if pattern in text:
            confidence -= decrement
    return max(0.3, min(1.0, confidence))


def detect_fraud_indicators_impl(claim_data: dict) -> str:
    """Check claim for fraud indicators. Returns JSON list of indicator strings."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return json.dumps(indicators)

    incident = (claim_data.get("incident_description") or "").strip().lower()
    damage = (claim_data.get("damage_description") or "").strip().lower()
    vin = (claim_data.get("vin") or "").strip()
    incident_date = (claim_data.get("incident_date") or "").strip()
    estimated_damage = claim_data.get("estimated_damage")
    if isinstance(estimated_damage, str):
        try:
            estimated_damage = float(estimated_damage)
        except ValueError:
            estimated_damage = None

    # Staged/fraud keywords from California compliance (multiple occupants, witnesses leave, prior claims, suspicious damage)
    fraud_keywords = [
        "staged", "multiple occupants", "witnesses left", "witness left",
        "prior claims", "suspicious damage", "inflated", "pre-existing",
        "inconsistent", "material misrepresentation",
    ]
    combined = f"{incident} {damage}"
    for kw in fraud_keywords:
        if kw in combined:
            indicators.append(kw.replace(" ", "_"))

    # Multiple claims on same VIN within 90 days
    if vin and incident_date:
        try:
            repo = ClaimRepository()
            from datetime import datetime as dt
            dt_obj = dt.strptime(incident_date, "%Y-%m-%d")
            start = (dt_obj - timedelta(days=ESCALATION_CONFIG["vin_claims_days"])).strftime("%Y-%m-%d")
            end = (dt_obj + timedelta(days=1)).strftime("%Y-%m-%d")
            matches = repo.search_claims(vin=vin, incident_date=None)
            same_vin = [m for m in matches if m.get("vin") == vin and m.get("incident_date") != incident_date]
            same_vin_in_window = [
                m for m in same_vin
                if m.get("incident_date") is not None and start <= m.get("incident_date") <= end
            ]
            if len(same_vin_in_window) >= 1:
                indicators.append("multiple_claims_same_vin")
        except (ValueError, OSError):  # date parse, DB file missing
            pass  # best-effort: skip multiple_claims check

    # Damage estimate significantly higher than vehicle value (need vehicle value)
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
                    if estimated_damage >= ESCALATION_CONFIG["fraud_damage_vs_value_ratio"] * vehicle_value:
                        indicators.append("damage_near_or_above_vehicle_value")
            except (json.JSONDecodeError, TypeError):
                # Best-effort: if vehicle value cannot be parsed, skip this specific fraud indicator.
                pass

    # Inconsistent descriptions: very low word overlap between incident and damage
    overlap_threshold = ESCALATION_CONFIG["description_overlap_threshold"]
    if incident and damage:
        words_i = set(incident.split())
        words_d = set(damage.split())
        if words_i and words_d:
            overlap = len(words_i & words_d) / len(words_i | words_d) if (words_i | words_d) else 0
            if overlap < overlap_threshold:
                indicators.append("incident_damage_description_mismatch")

    return json.dumps(indicators)


def compute_escalation_priority_impl(reasons: list[str], fraud_indicators: list[str]) -> str:
    """Compute escalation priority from reasons and fraud indicators. Returns JSON with 'priority' key."""
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
    claim_data: dict,
    router_output: str,
    similarity_score: float | None = None,
    payout_amount: float | None = None,
) -> str:
    """
    Evaluate claim for escalation. Returns JSON with needs_review, escalation_reasons,
    priority, fraud_indicators, recommended_action.
    """
    reasons: list[str] = []
    conf_threshold = ESCALATION_CONFIG["confidence_threshold"]
    high_value_threshold = ESCALATION_CONFIG["high_value_threshold"]
    low_sim, high_sim = ESCALATION_CONFIG["similarity_ambiguous_range"]

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

    fraud_json = detect_fraud_indicators_impl(claim_data or {})
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
