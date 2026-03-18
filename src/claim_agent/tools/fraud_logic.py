"""Fraud detection logic: pattern analysis, cross-reference, and assessment."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from claim_agent.adapters.registry import get_claim_search_adapter, get_siu_adapter
from claim_agent.compliance.state_rules import get_siu_referral_threshold
from claim_agent.config.settings import get_fraud_config
from claim_agent.db.repository import ClaimRepository
from claim_agent.tools.fraud_detectors import (
    INDICATOR_TO_PATTERN_SCORE,
    KNOWN_FRAUD_PATTERNS,
    run_fraud_detectors,
)
from claim_agent.tools.fraud_utils import as_trimmed_str, coerce_date
from claim_agent.tools.valuation_logic import fetch_vehicle_value_impl

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)


def analyze_claim_patterns_impl(
    claim_data: dict[str, Any],
    vin: Optional[str] = None,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Analyze claim for suspicious patterns."""
    if not claim_data or not isinstance(claim_data, dict):
        return json.dumps({
            "vin": vin or "",
            "patterns_detected": [],
            "timing_flags": [],
            "claim_history": [],
            "risk_factors": [],
            "pattern_score": 0,
        })

    result: dict[str, Any] = {
        "vin": vin or claim_data.get("vin", ""),
        "patterns_detected": [],
        "timing_flags": [],
        "claim_history": [],
        "risk_factors": [],
        "pattern_score": 0,
    }

    vin = vin or claim_data.get("vin", "").strip()
    incident_date_raw = claim_data.get("incident_date")
    if isinstance(incident_date_raw, datetime):
        incident_date = incident_date_raw.strftime("%Y-%m-%d")
    elif isinstance(incident_date_raw, date):
        incident_date = incident_date_raw.isoformat()
    elif isinstance(incident_date_raw, str):
        incident_date = (incident_date_raw or "").strip()
    else:
        incident_date = ""

    if vin:
        try:
            _repo = ctx.repo if ctx else ClaimRepository()
            all_claims = _repo.search_claims(vin=vin, incident_date=None)

            window_days = get_fraud_config()["multiple_claims_days"]
            if incident_date:
                try:
                    dt_obj = datetime.strptime(incident_date, "%Y-%m-%d")
                    start_date = (dt_obj - timedelta(days=window_days)).strftime("%Y-%m-%d")
                    end_date = (dt_obj + timedelta(days=1)).strftime("%Y-%m-%d")

                    claims_in_window = [
                        c
                        for c in all_claims
                        if (inc := c.get("incident_date")) is not None
                        and isinstance(inc, str)
                        and start_date <= inc <= end_date
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

    fraud_cfg = get_fraud_config()
    claim_id = as_trimmed_str(claim_data.get("claim_id"))

    # Run pluggable detectors and map indicators to pattern_score and risk_factors.
    indicators = run_fraud_detectors(claim_data, ctx)
    for ind in indicators:
        if ind in INDICATOR_TO_PATTERN_SCORE:
            pattern_name, config_key, risk_factor = INDICATOR_TO_PATTERN_SCORE[ind]
            if pattern_name not in result["patterns_detected"]:
                result["patterns_detected"].append(pattern_name)
                result["risk_factors"].append(risk_factor)
                result["pattern_score"] += int(fraud_cfg.get(config_key, 0))

    # Timing and staged keywords (simple checks, kept inline).
    incident_desc = (claim_data.get("incident_description") or "").lower()
    damage_desc = (claim_data.get("damage_description") or "").lower()
    combined_text = f"{incident_desc} {damage_desc}"

    for keyword in KNOWN_FRAUD_PATTERNS["timing_red_flags"]:
        if keyword in combined_text:
            result["timing_flags"].append(keyword)
            result["patterns_detected"].append("new_policy_timing")
            result["pattern_score"] += get_fraud_config()["timing_anomaly_score"]
            break

    for keyword in KNOWN_FRAUD_PATTERNS["staged_accident_keywords"]:
        if keyword in combined_text:
            result["patterns_detected"].append("staged_accident_indicators")
            result["risk_factors"].append(f"Staged accident keyword: '{keyword}'")
            result["pattern_score"] += get_fraud_config()["fraud_keyword_score"]
            break

    # Relationship analysis: fetch full snapshot for result (detector already ran it).
    if claim_id:
        try:
            repo = ctx.repo if ctx else ClaimRepository()
            relationship = repo.build_relationship_snapshot(
                claim_id=claim_id,
                max_nodes=int(fraud_cfg.get("graph_max_nodes", 100)),
                max_depth=int(fraud_cfg.get("graph_max_depth", 1)),
            )
            result["relationship_analysis"] = relationship
        except Exception as e:
            logger.debug("Relationship graph analysis skipped: %s", e)

    return json.dumps(result)


def cross_reference_fraud_indicators_impl(
    claim_data: dict[str, Any],
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Cross-reference claim against known fraud indicators database."""
    result: dict[str, Any] = {
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

    for keyword in KNOWN_FRAUD_PATTERNS["suspicious_claim_keywords"]:
        if keyword in combined_text:
            result["fraud_keywords_found"].append(keyword)
            result["cross_reference_score"] += get_fraud_config()["fraud_keyword_score"]

    for keyword in KNOWN_FRAUD_PATTERNS["damage_fraud_keywords"]:
        if keyword in combined_text:
            result["fraud_keywords_found"].append(keyword)
            result["cross_reference_score"] += get_fraud_config()["fraud_keyword_score"]

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
                val_result = fetch_vehicle_value_impl(vin, year, make, model, ctx=ctx)
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

    vin = claim_data.get("vin", "").strip()
    if vin:
        try:
            _repo = ctx.repo if ctx else ClaimRepository()
            prior_claims = _repo.search_claims(vin=vin, incident_date=None)
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

    fraud_cfg = get_fraud_config()
    xref_indicators = run_fraud_detectors(claim_data, ctx)
    if "provider_ring_suspected" in xref_indicators:
        result["database_matches"].append("provider_ring_suspected")
        result["recommendations"].append("Provider ring suspected across suspicious claims")
        result["cross_reference_score"] += int(fraud_cfg.get("provider_ring_score", 20))

    # ClaimSearch integration seam (NICB/ISO via adapter).
    search_terms = {
        "vin": as_trimmed_str(claim_data.get("vin")),
        "claimant_name": as_trimmed_str(claim_data.get("claimant_name")),
    }
    date_range: tuple[str, str] | None = None
    incident_dt = coerce_date(claim_data.get("incident_date"))
    if incident_dt:
        window_days = int(fraud_cfg.get("velocity_window_days", 30))
        start_dt = incident_dt - timedelta(days=window_days)
        end_dt = incident_dt + timedelta(days=window_days)
        date_range = (start_dt.strftime("%Y-%m-%d"), end_dt.strftime("%Y-%m-%d"))
    if search_terms["vin"] or search_terms["claimant_name"]:
        try:
            _claim_search = ctx.adapters.claim_search if ctx else get_claim_search_adapter()
            matches = _claim_search.search_claims(
                vin=search_terms["vin"] or None,
                claimant_name=search_terms["claimant_name"] or None,
                date_range=date_range,
            )
            if len(matches) >= int(fraud_cfg.get("claimsearch_match_threshold", 2)):
                result["database_matches"].append("cross_carrier_claimsearch_matches")
                result["recommendations"].append(
                    f"Found {len(matches)} cross-carrier claim-search match(es)"
                )
                result["cross_reference_score"] += int(fraud_cfg.get("claimsearch_match_score", 25))
        except NotImplementedError:
            logger.debug("ClaimSearch adapter stub in use; skipping external claim-search cross-reference")
        except Exception as e:
            logger.debug("ClaimSearch cross-reference skipped due to error: %s", e)

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
    photo_forensics: Optional[dict[str, Any]] = None,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Perform comprehensive fraud assessment combining pattern analysis and cross-reference results."""
    if not claim_data or not isinstance(claim_data, dict):
        return json.dumps({
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
            "mandatory_referral_applied": False,
            "state_referral_threshold": None,
        })

    result: dict[str, Any] = {
        "claim_id": claim_data.get("claim_id", ""),
        "fraud_score": 0,
        "fraud_likelihood": "low",
        "fraud_indicators": [],
        "pattern_flags": [],
        "cross_reference_flags": [],
        "recommended_action": "",
        "should_block": False,
        "siu_referral": False,
        "siu_case_id": None,
        "assessment_details": {},
        "mandatory_referral_applied": False,
        "state_referral_threshold": None,
    }

    if pattern_analysis is None:
        try:
            pattern_json = analyze_claim_patterns_impl(claim_data, ctx=ctx)
            pattern_analysis = json.loads(pattern_json)
        except (json.JSONDecodeError, TypeError):
            pattern_analysis = {}

    if cross_reference is None:
        try:
            xref_json = cross_reference_fraud_indicators_impl(claim_data, ctx=ctx)
            cross_reference = json.loads(xref_json)
        except (json.JSONDecodeError, TypeError):
            cross_reference = {}

    pattern_score = pattern_analysis.get("pattern_score", 0)
    xref_score = cross_reference.get("cross_reference_score", 0)
    result["fraud_score"] = pattern_score + xref_score

    result["pattern_flags"] = list(pattern_analysis.get("patterns_detected", []))
    result["cross_reference_flags"] = list(cross_reference.get("database_matches", []))
    combined_indicators: list[str] = (
        list(result["pattern_flags"])
        + list(result["cross_reference_flags"])
        + list(cross_reference.get("fraud_keywords_found", []))
    )
    seen_indicators = set()
    ordered_indicators = []
    for indicator in combined_indicators:
        if indicator not in seen_indicators:
            seen_indicators.add(indicator)
            ordered_indicators.append(indicator)
    result["fraud_indicators"] = ordered_indicators

    result["assessment_details"] = {
        "pattern_score": pattern_score,
        "cross_reference_score": xref_score,
        "claim_history_count": len(pattern_analysis.get("claim_history", [])),
        "risk_factors": pattern_analysis.get("risk_factors", []),
        "cross_reference_recommendations": cross_reference.get("recommendations", []),
    }

    fraud_cfg = get_fraud_config()
    if photo_forensics is None and isinstance(claim_data.get("photo_forensics"), dict):
        photo_forensics = claim_data.get("photo_forensics")
    if photo_forensics:
        anomalies = photo_forensics.get("anomalies", [])
        if isinstance(anomalies, list):
            normalized = [str(item) for item in anomalies if str(item).strip()]
        else:
            normalized = []
        if normalized:
            exif_score = int(fraud_cfg.get("photo_exif_anomaly_score", 10))
            result["fraud_score"] += exif_score * len(normalized)
            for anomaly in normalized:
                if anomaly not in result["fraud_indicators"]:
                    result["fraud_indicators"].append(anomaly)
            result["assessment_details"]["photo_forensics"] = {
                "anomalies": normalized,
                "score_added": exif_score * len(normalized),
            }

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

    # State-specific mandatory referral: when fraud score meets state threshold,
    # mandatory referral takes precedence (overrides any prior siu_referral from pattern analysis).
    state = (claim_data.get("state") or claim_data.get("loss_state") or "").strip()
    state_threshold = get_siu_referral_threshold(state) if state else None
    if state_threshold is not None and total_score >= state_threshold:
        result["siu_referral"] = True
        result["mandatory_referral_applied"] = True
        result["state_referral_threshold"] = state_threshold
        result["assessment_details"]["mandatory_referral_reason"] = (
            f"State {state} requires SIU referral when fraud score >= {state_threshold}"
        )
        if result["recommended_action"] and "SIU referral" not in result["recommended_action"]:
            result["recommended_action"] = (
                f"Mandatory SIU referral per state {state} (score {total_score} >= {state_threshold}). "
                + result["recommended_action"]
            )

    claim_id = result.get("claim_id")
    if result["siu_referral"] and claim_id and isinstance(claim_id, str) and claim_id.strip():
        _siu = ctx.adapters.siu if ctx else get_siu_adapter()
        try:
            case_id = _siu.create_case(claim_id, list(result["fraud_indicators"]))
            result["siu_case_id"] = case_id
            try:
                _repo = ctx.repo if ctx else ClaimRepository()
                _repo.update_claim_siu_case_id(claim_id, case_id)
                result["siu_case_id_persisted"] = True
            except Exception as e:
                result["siu_case_id_persisted"] = False
                logger.warning(
                    "Failed to persist siu_case_id for claim %s: %s",
                    claim_id,
                    e,
                    extra={"siu_case_id_persist_failed": True, "claim_id": claim_id},
                )
        except NotImplementedError:
            logger.warning(
                "SIU case creation not implemented (stub adapter); claim %s flagged for referral but no case_id",
                claim_id,
            )
            result["siu_case_id"] = None
    elif result["siu_referral"]:
        logger.warning(
            "SIU referral requested but no valid claim_id is available; skipping SIU case creation. Raw claim_id: %r",
            claim_id,
        )
        result["siu_case_id"] = None

    return json.dumps(result)
