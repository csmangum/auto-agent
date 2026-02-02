"""Shared logic for claim tools (used by both CrewAI tools and MCP server)."""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Optional

from claim_agent.config.settings import (
    DEFAULT_BASE_VALUE,
    DEFAULT_DEDUCTIBLE,
    DEPRECIATION_PER_YEAR,
    LABOR_HOURS_MIN,
    LABOR_HOURS_PAINT_BODY,
    LABOR_HOURS_RNI_PER_PART,
    MIN_PAYOUT_VEHICLE_VALUE,
    MIN_VEHICLE_VALUE,
    PARTIAL_LOSS_THRESHOLD,
    get_escalation_config,
    get_fraud_config,
)
from claim_agent.tools.data_loader import load_mock_db, load_california_compliance
from claim_agent.db.repository import ClaimRepository

# Set up logger
logger = logging.getLogger(__name__)


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


def compute_similarity_score_impl(description_a: str, description_b: str) -> float:
    """Compute Jaccard similarity (0–100) between two descriptions. Use this when only the score is needed to avoid JSON round-trip."""
    a = description_a.lower().strip()
    b = description_b.lower().strip()
    if not a or not b:
        return 0.0
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = len(words_a & words_b)
    union = len(words_a | words_b)
    return round((intersection / union) * 100.0, 2)


def compute_similarity_impl(description_a: str, description_b: str) -> str:
    score = compute_similarity_score_impl(description_a, description_b)
    return json.dumps({"similarity_score": score, "is_duplicate": score > 80.0})


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


def _gather_matches(
    data: dict[str, Any], query: str, section_key: str, matches: list[dict[str, Any]]
) -> None:
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
        logger.error("Policy lookup failed for policy %s: %s", policy_number, e, exc_info=True)
        return json.dumps({
            "error": "Policy lookup failed. Please try again.",
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
    decrement = get_escalation_config()["confidence_decrement_per_pattern"]
    for pattern in low_confidence_patterns:
        if pattern in text:
            confidence -= decrement
    return max(0.3, min(1.0, confidence))


def detect_fraud_indicators_impl(claim_data: dict[str, Any]) -> str:
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

    # Staged/fraud keywords from KNOWN_FRAUD_PATTERNS
    fraud_keywords = (
        KNOWN_FRAUD_PATTERNS["staged_accident_keywords"]
        + KNOWN_FRAUD_PATTERNS["suspicious_claim_keywords"]
    )
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
            start = (dt_obj - timedelta(days=get_escalation_config()["vin_claims_days"])).strftime("%Y-%m-%d")
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
                    if estimated_damage >= get_escalation_config()["fraud_damage_vs_value_ratio"] * vehicle_value:
                        indicators.append("damage_near_or_above_vehicle_value")
            except (json.JSONDecodeError, TypeError):
                # Best-effort: if vehicle value cannot be parsed, skip this specific fraud indicator.
                pass

    # Inconsistent descriptions: very low word overlap between incident and damage
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
    claim_data: dict[str, Any],
    router_output: str,
    similarity_score: float | None = None,
    payout_amount: float | None = None,
) -> str:
    """
    Evaluate claim for escalation. Returns JSON with needs_review, escalation_reasons,
    priority, fraud_indicators, recommended_action.
    """
    reasons: list[str] = []
    esc_config = get_escalation_config()
    conf_threshold = esc_config["confidence_threshold"]
    high_value_threshold = esc_config["high_value_threshold"]
    low_sim, high_sim = esc_config["similarity_ambiguous_range"]

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


# --- Fraud Detection ---

# Known fraud patterns and indicators database
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


def analyze_claim_patterns_impl(
    claim_data: dict[str, Any], vin: Optional[str] = None
) -> str:
    """
    Analyze claim for suspicious patterns including:
    - Multiple claims on same VIN within time window
    - Suspicious timing patterns (claims filed quickly, new policy claims)
    - Unusual claim frequency
    
    Returns JSON with pattern_analysis results.
    """
    if not claim_data or not isinstance(claim_data, dict):
        result = {
            "vin": vin or "",
            "patterns_detected": [],
            "timing_flags": [],
            "claim_history": [],
            "risk_factors": [],
            "pattern_score": 0,
        }
        return json.dumps(result)
    
    result = {
        "vin": vin or claim_data.get("vin", ""),
        "patterns_detected": [],
        "timing_flags": [],
        "claim_history": [],
        "risk_factors": [],
        "pattern_score": 0,
    }
    
    vin = vin or claim_data.get("vin", "").strip()
    incident_date = claim_data.get("incident_date", "").strip()
    
    # Check for multiple claims on same VIN
    if vin:
        try:
            repo = ClaimRepository()
            all_claims = repo.search_claims(vin=vin, incident_date=None)
            
            # Filter to claims within the time window
            window_days = get_fraud_config()["multiple_claims_days"]
            if incident_date:
                try:
                    dt_obj = datetime.strptime(incident_date, "%Y-%m-%d")
                    start_date = (dt_obj - timedelta(days=window_days)).strftime("%Y-%m-%d")
                    end_date = (dt_obj + timedelta(days=1)).strftime("%Y-%m-%d")
                    
                    claims_in_window = [
                        c for c in all_claims
                        if c.get("incident_date") and start_date <= c.get("incident_date") <= end_date
                    ]
                    
                    result["claim_history"] = [
                        {
                            "claim_id": c.get("id"),
                            "incident_date": c.get("incident_date"),
                            "status": c.get("status", "unknown"),
                        }
                        for c in claims_in_window
                    ]
                    
                    if len(claims_in_window) >= get_fraud_config()["multiple_claims_threshold"]:
                        result["patterns_detected"].append("multiple_claims_same_vin")
                        result["risk_factors"].append(
                            f"Found {len(claims_in_window)} claims on VIN within {window_days} days"
                        )
                        result["pattern_score"] += get_fraud_config()["multiple_claims_score"]
                except (ValueError, TypeError) as e:
                    logger.debug(
                        "Skipping VIN claim history window calculation due to invalid incident_date %r: %s",
                        incident_date,
                        e,
                    )
        except Exception as e:
            logger.debug("Best-effort pattern analysis: could not search claims by VIN: %s", e)
    
    # Check for suspicious timing
    incident_desc = (claim_data.get("incident_description") or "").lower()
    damage_desc = (claim_data.get("damage_description") or "").lower()
    combined_text = f"{incident_desc} {damage_desc}"
    
    for keyword in KNOWN_FRAUD_PATTERNS["timing_red_flags"]:
        if keyword in combined_text:
            result["timing_flags"].append(keyword)
            result["patterns_detected"].append("new_policy_timing")
            result["pattern_score"] += get_fraud_config()["timing_anomaly_score"]
            break
    
    # Check for staged accident patterns
    for keyword in KNOWN_FRAUD_PATTERNS["staged_accident_keywords"]:
        if keyword in combined_text:
            result["patterns_detected"].append("staged_accident_indicators")
            result["risk_factors"].append(f"Staged accident keyword: '{keyword}'")
            result["pattern_score"] += get_fraud_config()["fraud_keyword_score"]
            break
    
    return json.dumps(result)


def cross_reference_fraud_indicators_impl(claim_data: dict[str, Any]) -> str:
    """
    Cross-reference claim against known fraud indicators database:
    - Fraud keywords in descriptions
    - Damage vs vehicle value mismatch
    - Prior fraud flags on VIN or policy
    
    Returns JSON with cross_reference results.
    """
    result = {
        "fraud_keywords_found": [],
        "database_matches": [],
        "risk_level": "low",
        "cross_reference_score": 0,
        "recommendations": [],
    }
    
    if not claim_data or not isinstance(claim_data, dict):
        return json.dumps(result)
    
    incident_desc = (claim_data.get("incident_description") or "").lower()
    damage_desc = (claim_data.get("damage_description") or "").lower()
    combined_text = f"{incident_desc} {damage_desc}"
    
    # Check for suspicious claim keywords
    for keyword in KNOWN_FRAUD_PATTERNS["suspicious_claim_keywords"]:
        if keyword in combined_text:
            result["fraud_keywords_found"].append(keyword)
            result["cross_reference_score"] += get_fraud_config()["fraud_keyword_score"]
    
    # Check for damage fraud keywords
    for keyword in KNOWN_FRAUD_PATTERNS["damage_fraud_keywords"]:
        if keyword in combined_text:
            result["fraud_keywords_found"].append(keyword)
            result["cross_reference_score"] += get_fraud_config()["fraud_keyword_score"]
    
    # Check damage estimate vs vehicle value
    estimated_damage = claim_data.get("estimated_damage")
    if isinstance(estimated_damage, str):
        try:
            estimated_damage = float(estimated_damage)
        except ValueError:
            estimated_damage = None
    
    if estimated_damage and estimated_damage > 0:
        vin = claim_data.get("vin", "").strip()
        year = claim_data.get("vehicle_year")
        make = claim_data.get("vehicle_make") or claim_data.get("make") or ""
        model = claim_data.get("vehicle_model") or claim_data.get("model") or ""
        
        if year and make and model:
            try:
                val_result = fetch_vehicle_value_impl(vin, year, make, model)
                val_data = json.loads(val_result)
                vehicle_value = val_data.get("value")
                
                if vehicle_value and vehicle_value > 0:
                    damage_ratio = estimated_damage / vehicle_value
                    
                    if damage_ratio > 1.0:
                        result["database_matches"].append("damage_exceeds_vehicle_value")
                        result["recommendations"].append(
                            f"Damage estimate (${estimated_damage:,.0f}) exceeds vehicle value (${vehicle_value:,.0f})"
                        )
                        result["cross_reference_score"] += get_fraud_config()["damage_mismatch_score"]
                    elif damage_ratio > 0.9:
                        result["database_matches"].append("damage_near_vehicle_value")
                        result["recommendations"].append(
                            "Damage estimate is near total vehicle value - verify accuracy"
                        )
                        result["cross_reference_score"] += get_fraud_config()["damage_mismatch_score"] // 2
            except (json.JSONDecodeError, TypeError) as e:
                logger.debug("Skipping damage vs value check due to valuation/type error: %s", e)
    
    # Check for prior fraud claims on same VIN
    vin = claim_data.get("vin", "").strip()
    if vin:
        try:
            repo = ClaimRepository()
            prior_claims = repo.search_claims(vin=vin, incident_date=None)
            fraud_history = [
                c for c in prior_claims
                if c.get("status") in ("fraud_suspected", "fraud_confirmed")
            ]
            
            if fraud_history:
                result["database_matches"].append("prior_fraud_history")
                result["recommendations"].append(
                    f"VIN has {len(fraud_history)} prior fraud-flagged claim(s)"
                )
                result["cross_reference_score"] += get_fraud_config()["multiple_claims_score"]
        except Exception as e:
            logger.debug("Best-effort cross-reference: could not check prior fraud claims for VIN: %s", e)
    
    # Determine risk level
    score = result["cross_reference_score"]
    if score >= get_fraud_config()["high_risk_threshold"]:
        result["risk_level"] = "high"
        result["recommendations"].append("Refer to Special Investigations Unit (SIU)")
    elif score >= get_fraud_config()["medium_risk_threshold"]:
        result["risk_level"] = "medium"
        result["recommendations"].append("Flag for manual review before processing")
    else:
        result["risk_level"] = "low"
    
    return json.dumps(result)


def perform_fraud_assessment_impl(
    claim_data: dict[str, Any],
    pattern_analysis: Optional[dict[str, Any]] = None,
    cross_reference: Optional[dict[str, Any]] = None,
) -> str:
    """
    Perform comprehensive fraud assessment combining pattern analysis and cross-reference results.
    
    Returns JSON with final fraud assessment including:
    - fraud_score: Combined risk score
    - fraud_likelihood: low/medium/high/critical
    - fraud_indicators: List of all detected indicators
    - recommended_action: What to do next
    - should_block: Whether claim should be blocked
    - siu_referral: Whether to refer to SIU
    """
    if not claim_data or not isinstance(claim_data, dict):
        result = {
            "claim_id": "",
            "fraud_score": 0,
            "fraud_likelihood": "low",
            "fraud_indicators": [],
            "pattern_flags": [],
            "cross_reference_flags": [],
            "recommended_action": "Invalid claim data - manual review required",
            "should_block": False,
            "siu_referral": False,
            "assessment_details": {},
        }
        return json.dumps(result)
    
    result = {
        "claim_id": claim_data.get("claim_id", ""),
        "fraud_score": 0,
        "fraud_likelihood": "low",
        "fraud_indicators": [],
        "pattern_flags": [],
        "cross_reference_flags": [],
        "recommended_action": "",
        "should_block": False,
        "siu_referral": False,
        "assessment_details": {},
    }
    
    # Get pattern analysis if not provided
    if pattern_analysis is None:
        try:
            pattern_json = analyze_claim_patterns_impl(claim_data)
            pattern_analysis = json.loads(pattern_json)
        except (json.JSONDecodeError, TypeError):
            pattern_analysis = {}
    
    # Get cross-reference if not provided
    if cross_reference is None:
        try:
            xref_json = cross_reference_fraud_indicators_impl(claim_data)
            cross_reference = json.loads(xref_json)
        except (json.JSONDecodeError, TypeError):
            cross_reference = {}
    
    # Combine scores
    pattern_score = pattern_analysis.get("pattern_score", 0)
    xref_score = cross_reference.get("cross_reference_score", 0)
    result["fraud_score"] = pattern_score + xref_score
    
    # Collect all indicators (ordered dedup for stable output)
    result["pattern_flags"] = pattern_analysis.get("patterns_detected", [])
    result["cross_reference_flags"] = cross_reference.get("database_matches", [])
    combined_indicators = (
        result["pattern_flags"]
        + result["cross_reference_flags"]
        + cross_reference.get("fraud_keywords_found", [])
    )
    seen_indicators = set()
    ordered_indicators = []
    for indicator in combined_indicators:
        if indicator not in seen_indicators:
            seen_indicators.add(indicator)
            ordered_indicators.append(indicator)
    result["fraud_indicators"] = ordered_indicators
    
    # Store details
    result["assessment_details"] = {
        "pattern_score": pattern_score,
        "cross_reference_score": xref_score,
        "claim_history_count": len(pattern_analysis.get("claim_history", [])),
        "risk_factors": pattern_analysis.get("risk_factors", []),
        "cross_reference_recommendations": cross_reference.get("recommendations", []),
    }
    
    # Determine fraud likelihood and actions
    total_score = result["fraud_score"]
    indicator_count = len(result["fraud_indicators"])
    
    if total_score >= get_fraud_config()["critical_risk_threshold"] or indicator_count >= get_fraud_config()["critical_indicator_count"]:
        result["fraud_likelihood"] = "critical"
        result["should_block"] = True
        result["siu_referral"] = True
        result["recommended_action"] = (
            "BLOCK CLAIM. Critical fraud risk detected. "
            "Immediate SIU referral required. Do not process payment."
        )
    elif total_score >= get_fraud_config()["high_risk_threshold"] or indicator_count >= 3:
        result["fraud_likelihood"] = "high"
        result["should_block"] = False
        result["siu_referral"] = True
        result["recommended_action"] = (
            "High fraud risk. Refer to SIU before proceeding. "
            "Gather additional documentation. Conduct recorded statement."
        )
    elif total_score >= get_fraud_config()["medium_risk_threshold"] or indicator_count >= 2:
        result["fraud_likelihood"] = "medium"
        result["should_block"] = False
        result["siu_referral"] = False
        result["recommended_action"] = (
            "Elevated fraud risk. Assign to senior adjuster. "
            "Verify all documentation. Request additional evidence."
        )
    else:
        result["fraud_likelihood"] = "low"
        result["should_block"] = False
        result["siu_referral"] = False
        result["recommended_action"] = (
            "Low fraud risk. Process claim per standard workflow. "
            "Document any minor discrepancies."
        )
    
    return json.dumps(result)


# --- Partial Loss Tools ---


def _get_shop_labor_rate(
    db: dict[str, Any], shop_id: Optional[str], default: float = 75.0
) -> float:
    """Return labor rate for shop_id from db, or default if not found."""
    if not shop_id:
        return default
    shops = db.get("repair_shops", {})
    if shop_id not in shops:
        return default
    return shops[shop_id].get("labor_rate_per_hour", default)


def get_available_repair_shops_impl(
    location: Optional[str] = None,
    vehicle_make: Optional[str] = None,
    network_type: Optional[str] = None,
) -> str:
    """Get list of available repair shops, optionally filtered by location, vehicle make, or network type.
    
    Args:
        location: Optional location filter (city/state).
        vehicle_make: Optional vehicle make to find shops with certifications for that make.
        network_type: Optional network type filter (preferred, premium, standard).
    
    Returns:
        JSON string with list of available repair shops.
    """
    db = load_mock_db()
    shops = db.get("repair_shops", {})
    
    available_shops = []
    for shop_id, shop_data in shops.items():
        # Filter by availability
        if not shop_data.get("capacity_available", False):
            continue
        
        # Filter by network type if specified
        if network_type and shop_data.get("network", "").lower() != network_type.lower():
            continue
        
        # Filter by location if specified (simple substring match)
        if location:
            shop_address = shop_data.get("address", "").lower()
            if location.lower() not in shop_address:
                continue
        
        # Check for EV/specialty certifications if Tesla
        if vehicle_make and vehicle_make.lower() == "tesla":
            certifications = shop_data.get("certifications", [])
            specialties = shop_data.get("specialties", [])
            has_ev_cert = (any("tesla" in c.lower() for c in certifications) or 
                          any("electric" in s.lower() for s in specialties))
            # Prefer shops with EV capability but don't exclude others
            shop_data = {**shop_data, "ev_certified": has_ev_cert}
        
        available_shops.append({
            "shop_id": shop_id,
            **shop_data,
        })
    
    # Sort by rating (highest first), then by wait time (lowest first)
    available_shops.sort(key=lambda x: (-x.get("rating", 0), x.get("average_wait_days", 999)))
    
    return json.dumps({
        "shop_count": len(available_shops),
        "shops": available_shops,
    })


def assign_repair_shop_impl(
    claim_id: str,
    shop_id: str,
    estimated_repair_days: Optional[int] = None,
) -> str:
    """Assign a repair shop to a partial loss claim.
    
    Args:
        claim_id: The claim ID to assign the shop to.
        shop_id: The repair shop ID to assign.
        estimated_repair_days: Optional estimated days to complete repair.
    
    Returns:
        JSON string with assignment confirmation and details.
    """
    db = load_mock_db()
    shops = db.get("repair_shops", {})
    
    if shop_id not in shops:
        return json.dumps({
            "success": False,
            "error": f"Repair shop {shop_id} not found",
        })
    
    shop = shops[shop_id]
    
    if not shop.get("capacity_available", False):
        return json.dumps({
            "success": False,
            "error": f"Repair shop {shop['name']} does not have available capacity",
        })
    
    # Calculate estimated dates
    wait_days = shop.get("average_wait_days", 3)
    repair_days = estimated_repair_days or 5  # Default 5 days for repair
    
    start_date = datetime.now() + timedelta(days=wait_days)
    completion_date = start_date + timedelta(days=repair_days)
    
    assignment = {
        "success": True,
        "claim_id": claim_id,
        "shop_id": shop_id,
        "shop_name": shop.get("name", ""),
        "address": shop.get("address", ""),
        "phone": shop.get("phone", ""),
        "labor_rate_per_hour": _get_shop_labor_rate(db, shop_id, 75.0),
        "network": shop.get("network", "standard"),
        "estimated_start_date": start_date.strftime("%Y-%m-%d"),
        "estimated_completion_date": completion_date.strftime("%Y-%m-%d"),
        "confirmation_number": f"RSA-{uuid.uuid4().hex[:8].upper()}",
    }
    
    return json.dumps(assignment)


def get_parts_catalog_impl(
    damage_description: str,
    vehicle_make: str,
    part_type_preference: str = "aftermarket",
) -> str:
    """Get recommended parts from catalog based on damage description.
    
    Args:
        damage_description: Description of the damage to identify needed parts.
        vehicle_make: Vehicle manufacturer to check part compatibility.
        part_type_preference: Preferred part type (oem, aftermarket, refurbished).
    
    Returns:
        JSON string with list of recommended parts and pricing.
    """
    db = load_mock_db()
    parts_catalog = db.get("parts_catalog", {})
    
    # Keyword mapping to parts (more specific keywords first to prevent incorrect matches)
    damage_to_parts = {
        "front bumper": ["PART-BUMPER-FRONT"],
        "rear bumper": ["PART-BUMPER-REAR"],
        "front door": ["PART-DOOR-FRONT"],
        "rear door": ["PART-DOOR-REAR"],
        "side mirror": ["PART-MIRROR-SIDE"],
        "quarter panel": ["PART-QUARTER-PANEL"],
        "bumper": ["PART-BUMPER-FRONT", "PART-BUMPER-REAR"],
        "fender": ["PART-FENDER-FRONT"],
        "hood": ["PART-HOOD"],
        "door": ["PART-DOOR-FRONT", "PART-DOOR-REAR"],
        "headlight": ["PART-HEADLIGHT"],
        "taillight": ["PART-TAILLIGHT"],
        "mirror": ["PART-MIRROR-SIDE"],
        "windshield": ["PART-WINDSHIELD"],
        "radiator": ["PART-RADIATOR"],
        "airbag": ["PART-AIRBAG-DRIVER", "PART-AIRBAG-PASSENGER"],
        "grille": ["PART-GRILLE"],
        "trunk": ["PART-TRUNK-LID"],
    }
    
    damage_lower = damage_description.lower()
    recommended_parts = []
    seen_part_ids = set()
    # Iterate by descending keyword length so more specific phrases (e.g. "front bumper")
    # match before generic ones (e.g. "bumper"), avoiding over-broad matches.
    for keyword, part_ids in sorted(damage_to_parts.items(), key=lambda kv: len(kv[0]), reverse=True):
        if keyword not in damage_lower:
            continue
        # Skip generic keyword if a more specific phrase is present (e.g. "bumper" when "front bumper" is in text)
        if keyword == "bumper" and ("front bumper" in damage_lower or "rear bumper" in damage_lower):
            continue
        if keyword == "door" and ("front door" in damage_lower or "rear door" in damage_lower):
            continue
        if keyword == "mirror" and "side mirror" in damage_lower:
            continue
        for part_id in part_ids:
            if part_id in seen_part_ids:
                continue
            seen_part_ids.add(part_id)

            if part_id in parts_catalog:
                part = parts_catalog[part_id]

                # Check vehicle make compatibility (case-insensitive)
                compatible_makes = part.get("compatible_makes", [])
                vehicle_make_norm = (
                    vehicle_make.strip().lower() if isinstance(vehicle_make, str) else ""
                )
                compatible_norm = [
                    m.strip().lower() for m in compatible_makes if isinstance(m, str)
                ]
                is_compatible = (
                    not compatible_makes or vehicle_make_norm in compatible_norm
                )

                # Get price based on preference
                selected_type = part_type_preference
                if part_type_preference == "oem":
                    price = part.get("oem_price")
                elif part_type_preference == "refurbished":
                    price = part.get("refurbished_price") or part.get("aftermarket_price")
                else:
                    price = part.get("aftermarket_price") or part.get("oem_price")

                if price is None:
                    price = part.get("oem_price", 0)
                    selected_type = "oem"  # Fall back to OEM if no alternative

                recommended_parts.append({
                    "part_id": part_id,
                    "part_name": part.get("name", ""),
                    "category": part.get("category", ""),
                    "selected_type": selected_type,
                    "price": price,
                    "oem_price": part.get("oem_price"),
                    "aftermarket_price": part.get("aftermarket_price"),
                    "refurbished_price": part.get("refurbished_price"),
                    "availability": part.get("availability", "unknown"),
                    "lead_time_days": part.get("lead_time_days", 3),
                    "is_compatible": is_compatible,
                })
    
    total_cost = sum(p["price"] for p in recommended_parts if p["price"])
    
    return json.dumps({
        "damage_description": damage_description,
        "vehicle_make": vehicle_make,
        "part_type_preference": part_type_preference,
        "parts_count": len(recommended_parts),
        "parts": recommended_parts,
        "total_parts_cost": round(total_cost, 2),
    })


def create_parts_order_impl(
    claim_id: str,
    parts: list[dict],
    shop_id: str | None = None,
) -> str:
    """Create a parts order for a partial loss claim.
    
    Args:
        claim_id: The claim ID for the order.
        parts: List of parts to order (each with part_id, quantity, part_type).
        shop_id: Optional shop ID for delivery.
    
    Returns:
        JSON string with order confirmation and details.
    """
    if not parts or not isinstance(parts, list):
        return json.dumps({
            "success": False,
            "error": "No parts specified for order",
        })
    
    db = load_mock_db()
    parts_catalog = db.get("parts_catalog", {})
    
    order_items = []
    total_cost = 0.0
    max_lead_time = 0
    
    for part_request in parts:
        part_id = part_request.get("part_id", "")
        quantity = part_request.get("quantity", 1)
        part_type = part_request.get("part_type", "aftermarket")
        
        if part_id not in parts_catalog:
            continue
        
        part = parts_catalog[part_id]
        
        # Get price based on type preference
        if part_type == "oem":
            unit_price = part.get("oem_price")
        elif part_type == "refurbished":
            unit_price = part.get("refurbished_price") or part.get("aftermarket_price")
        else:
            unit_price = part.get("aftermarket_price") or part.get("oem_price")
        
        if unit_price is None:
            unit_price = part.get("oem_price", 0)
        
        item_total = unit_price * quantity
        lead_time = part.get("lead_time_days", 3)
        max_lead_time = max(max_lead_time, lead_time)
        
        order_items.append({
            "part_id": part_id,
            "part_name": part.get("name", ""),
            "quantity": quantity,
            "part_type": part_type,
            "unit_price": unit_price,
            "total_price": round(item_total, 2),
            "availability": part.get("availability", "unknown"),
            "lead_time_days": lead_time,
        })
        
        total_cost += item_total
    
    if not order_items:
        return json.dumps({
            "success": False,
            "error": "No valid parts found in catalog",
        })
    
    delivery_date = datetime.now() + timedelta(days=max_lead_time + 1)
    
    order = {
        "success": True,
        "order_id": f"PO-{uuid.uuid4().hex[:8].upper()}",
        "claim_id": claim_id,
        "shop_id": shop_id,
        "items": order_items,
        "items_count": len(order_items),
        "total_parts_cost": round(total_cost, 2),
        "order_status": "ordered",
        "estimated_delivery_date": delivery_date.strftime("%Y-%m-%d"),
        "order_placed_at": datetime.now().isoformat(),
    }
    
    return json.dumps(order)


def calculate_repair_estimate_impl(
    damage_description: str,
    vehicle_make: str,
    vehicle_year: int,
    policy_number: str,
    shop_id: Optional[str] = None,
    part_type_preference: str = "aftermarket",
) -> str:
    """Calculate a complete repair estimate for a partial loss claim.
    
    Args:
        damage_description: Description of the damage.
        vehicle_make: Vehicle manufacturer.
        vehicle_year: Vehicle year.
        policy_number: Policy number to look up deductible.
        shop_id: Optional shop ID to use shop's labor rate.
        part_type_preference: Preferred part type (oem, aftermarket, refurbished).
    
    Returns:
        JSON string with complete repair estimate breakdown.
    """
    db = load_mock_db()

    # Get parts cost
    parts_result = get_parts_catalog_impl(damage_description, vehicle_make, part_type_preference)
    parts_data = json.loads(parts_result)
    parts_cost = parts_data.get("total_parts_cost", 0.0)
    parts_list = parts_data.get("parts", [])

    labor_rate = _get_shop_labor_rate(db, shop_id, 75.0)

    # Estimate labor hours based on damage and parts
    labor_operations = db.get("labor_operations", {})
    base_labor_hours = 0.0
    damage_lower = damage_description.lower()
    
    # Add labor for each part (R&I + paint typically)
    has_body_part = False
    for part in parts_list:
        base_labor_hours += LABOR_HOURS_RNI_PER_PART
        if part.get("category") == "body":
            base_labor_hours += LABOR_HOURS_PAINT_BODY
            has_body_part = True

    # Add specific labor operations based on damage (avoid double-counting paint:
    # only add blend when paint/scratch mentioned but no body part already got paint labor)
    if ("paint" in damage_lower or "scratch" in damage_lower) and not has_body_part:
        base_labor_hours += labor_operations.get("LABOR-BLEND-PAINT", {}).get("base_hours", LABOR_HOURS_PAINT_BODY)
    if "dent" in damage_lower and "minor" in damage_lower:
        base_labor_hours += labor_operations.get("LABOR-PDR", {}).get("base_hours", 1.0)
    if "frame" in damage_lower:
        base_labor_hours += labor_operations.get("LABOR-FRAME-PULL", {}).get("base_hours", 3.0)
    if "alignment" in damage_lower or "wheel" in damage_lower:
        base_labor_hours += labor_operations.get("LABOR-ALIGNMENT", {}).get("base_hours", 1.0)
    if "sensor" in damage_lower or "camera" in damage_lower or "adas" in damage_lower:
        base_labor_hours += labor_operations.get("LABOR-CALIBRATION", {}).get("base_hours", LABOR_HOURS_PAINT_BODY)

    if base_labor_hours < LABOR_HOURS_MIN:
        base_labor_hours = LABOR_HOURS_MIN
    
    labor_cost = round(base_labor_hours * labor_rate, 2)
    total_estimate = round(parts_cost + labor_cost, 2)
    
    # Get deductible from policy
    policy_result = query_policy_db_impl(policy_number)
    policy_data = json.loads(policy_result)
    deductible = policy_data.get("deductible", DEFAULT_DEDUCTIBLE) if policy_data.get("valid") else DEFAULT_DEDUCTIBLE
    
    customer_pays = min(deductible, total_estimate)
    insurance_pays = max(0, total_estimate - deductible)
    
    # Check if this is actually a total loss
    vin = ""  # We don't have VIN in this function, use year/make/model
    vehicle_value_result = fetch_vehicle_value_impl(vin, vehicle_year, vehicle_make, "")
    vehicle_value_data = json.loads(vehicle_value_result)
    vehicle_value = vehicle_value_data.get("value", 15000)
    
    is_total_loss = total_estimate >= (PARTIAL_LOSS_THRESHOLD * vehicle_value)
    
    estimate = {
        "damage_description": damage_description,
        "vehicle_make": vehicle_make,
        "vehicle_year": vehicle_year,
        "parts": parts_list,
        "parts_cost": parts_cost,
        "labor_hours": round(base_labor_hours, 1),
        "labor_rate": labor_rate,
        "labor_cost": labor_cost,
        "total_estimate": total_estimate,
        "deductible": deductible,
        "customer_pays": customer_pays,
        "insurance_pays": insurance_pays,
        "vehicle_value": vehicle_value,
        "repair_to_value_ratio": round(total_estimate / vehicle_value, 2) if vehicle_value > 0 else 0,
        "is_total_loss": is_total_loss,
        "total_loss_threshold": PARTIAL_LOSS_THRESHOLD,
        "part_type_preference": part_type_preference,
        "shop_id": shop_id,
    }
    
    return json.dumps(estimate)


def generate_repair_authorization_impl(
    claim_id: str,
    shop_id: str,
    repair_estimate: dict[str, Any],
    customer_approved: bool = True,
) -> str:
    """Generate a repair authorization document for a partial loss claim.
    
    Args:
        claim_id: The claim ID.
        shop_id: The assigned repair shop ID.
        repair_estimate: The repair estimate details.
        customer_approved: Whether customer has approved the repair.
    
    Returns:
        JSON string with repair authorization details.
    """
    db = load_mock_db()
    shops = db.get("repair_shops", {})
    
    shop = shops.get(shop_id, {})
    
    authorization = {
        "authorization_id": f"RA-{uuid.uuid4().hex[:8].upper()}",
        "claim_id": claim_id,
        "shop_id": shop_id,
        "shop_name": shop.get("name", "Unknown Shop"),
        "shop_address": shop.get("address", ""),
        "shop_phone": shop.get("phone", ""),
        "authorized_amount": repair_estimate.get("total_estimate", 0),
        "parts_authorized": repair_estimate.get("parts_cost", 0),
        "labor_authorized": repair_estimate.get("labor_cost", 0),
        "deductible": repair_estimate.get("deductible", 0),
        "customer_responsibility": repair_estimate.get("customer_pays", 0),
        "insurance_responsibility": repair_estimate.get("insurance_pays", 0),
        "customer_approved": customer_approved,
        "authorization_status": "approved" if customer_approved else "pending_approval",
        "authorization_date": datetime.now().strftime("%Y-%m-%d"),
        "valid_until": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "terms": [
            "Repair must be completed within 30 days of authorization",
            "Any additional damage found must be reported before repair",
            "Supplemental authorization required for additional costs over 10%",
            "Original damaged parts must be retained for inspection if requested",
        ],
    }
    
    return json.dumps(authorization)
