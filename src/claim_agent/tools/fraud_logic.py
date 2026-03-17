"""Fraud detection logic: pattern analysis, cross-reference, and assessment."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from claim_agent.adapters.registry import get_claim_search_adapter, get_siu_adapter
from claim_agent.config.settings import get_fraud_config
from claim_agent.db.repository import ClaimRepository
from claim_agent.tools.fraud_detectors import KNOWN_FRAUD_PATTERNS
from claim_agent.tools.fraud_utils import _as_nonempty_str, _coerce_date
from claim_agent.tools.valuation_logic import fetch_vehicle_value_impl

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)


def _extract_provider_names(claim_data: dict[str, Any], repo: ClaimRepository) -> list[str]:
    names: set[str] = set()
    for key in (
        "provider_name",
        "repair_shop_name",
        "medical_provider_name",
        "doctor_name",
        "body_shop_name",
    ):
        raw = claim_data.get(key)
        if isinstance(raw, str) and raw.strip():
            names.add(raw.strip())

    for key in ("provider_names", "medical_providers", "repair_shops"):
        raw = claim_data.get(key)
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, str) and item.strip():
                names.add(item.strip())
            elif isinstance(item, dict):
                for nested_key in ("name", "provider_name", "shop_name"):
                    nested = item.get(nested_key)
                    if isinstance(nested, str) and nested.strip():
                        names.add(nested.strip())
                        break

    claim_id = _as_nonempty_str(claim_data.get("claim_id"))
    if claim_id:
        try:
            parties = repo.get_claim_parties(claim_id, party_type="provider")
            for party in parties:
                party_name = _as_nonempty_str(party.get("name"))
                if party_name:
                    names.add(party_name)
        except Exception as e:
            logger.debug("Unable to load provider parties for claim %s: %s", claim_id, e)

    return sorted(names)


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

    repo = ctx.repo if ctx else ClaimRepository()
    fraud_cfg = get_fraud_config()
    claim_id = _as_nonempty_str(claim_data.get("claim_id"))
    incident_dt = _coerce_date(claim_data.get("incident_date"))

    # Velocity checks: multiple claims from same address across different policies.
    addresses: set[str] = set()
    for key in ("claimant_address", "policy_address", "garaging_address"):
        address = _as_nonempty_str(claim_data.get(key))
        if address:
            addresses.add(address)
    if claim_id:
        try:
            parties = repo.get_claim_parties(claim_id)
            for party in parties:
                address = _as_nonempty_str(party.get("address"))
                if address:
                    addresses.add(address)
        except Exception as e:
            logger.debug("Could not load claim parties for velocity analysis: %s", e)
    velocity_hits: list[dict[str, Any]] = []
    velocity_hit_ids: set[str] = set()
    if incident_dt and addresses:
        window_days = int(fraud_cfg.get("velocity_window_days", 30))
        for address in addresses:
            try:
                related = repo.get_claims_by_party_address(address, limit=100)
            except Exception as e:
                logger.debug("Velocity lookup failed for address %r: %s", address, e)
                continue
            for row in related:
                related_id = _as_nonempty_str(row.get("id"))
                if claim_id and related_id == claim_id:
                    continue
                if related_id in velocity_hit_ids:
                    continue
                related_dt = _coerce_date(row.get("incident_date"))
                if related_dt is None:
                    continue
                if abs((incident_dt - related_dt).days) <= window_days:
                    velocity_hits.append(row)
                    velocity_hit_ids.add(related_id)
        distinct_policies = {
            _as_nonempty_str(item.get("policy_number"))
            for item in velocity_hits
            if _as_nonempty_str(item.get("policy_number"))
        }
        threshold = int(fraud_cfg.get("velocity_claim_threshold", 2))
        if len(velocity_hits) >= threshold and len(distinct_policies) >= 2:
            result["patterns_detected"].append("high_velocity_same_address")
            result["risk_factors"].append(
                f"Address-linked velocity: {len(velocity_hits)} nearby claims across "
                f"{len(distinct_policies)} policies"
            )
            result["pattern_score"] += int(fraud_cfg.get("velocity_score", 20))

    # Geographic anomaly checks.
    policy_state = _as_nonempty_str(claim_data.get("policy_state"))
    loss_state = _as_nonempty_str(claim_data.get("loss_state") or claim_data.get("incident_state"))
    repair_state = _as_nonempty_str(claim_data.get("repair_shop_state"))
    nonempty_states = [state for state in (policy_state, loss_state, repair_state) if state]
    if len(nonempty_states) >= 2 and len(set(nonempty_states)) > 1:
        result["patterns_detected"].append("geographic_state_inconsistency")
        result["risk_factors"].append(
            f"State mismatch detected across policy/loss/repair locations: {sorted(set(nonempty_states))}"
        )
        result["pattern_score"] += int(fraud_cfg.get("geographic_anomaly_score", 15))

    # Relationship graph analysis via migration-ready repository APIs.
    if claim_id:
        try:
            relationship = repo.build_relationship_snapshot(
                claim_id=claim_id,
                max_depth=int(fraud_cfg.get("graph_max_depth", 2)),
                max_nodes=int(fraud_cfg.get("graph_max_nodes", 100)),
            )
            if relationship.get("dense_cluster_detected"):
                result["patterns_detected"].append("relationship_graph_dense_cluster")
                result["risk_factors"].append("Dense relationship cluster detected")
                result["pattern_score"] += int(fraud_cfg.get("graph_cluster_score", 25))
            high_risk_links = int(relationship.get("high_risk_link_count", 0))
            if high_risk_links >= int(fraud_cfg.get("graph_high_risk_link_threshold", 2)):
                result["patterns_detected"].append("relationship_graph_high_risk_links")
                result["risk_factors"].append(
                    f"Relationship graph has {high_risk_links} high-risk links"
                )
                result["pattern_score"] += int(fraud_cfg.get("graph_high_risk_score", 20))
            result["relationship_analysis"] = relationship
        except Exception as e:
            logger.debug("Relationship graph analysis skipped: %s", e)

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

    occupant_markers = ("multiple occupants", "all passengers", "all injured", "whiplash")
    intersection_markers = ("intersection", "4-way", "four-way", "stop sign", "traffic light")
    sudden_stop_markers = ("sudden stop", "brake checked", "rear-ended at low speed")
    has_occupants = any(marker in incident_desc for marker in occupant_markers)
    has_intersection = any(marker in incident_desc for marker in intersection_markers)
    has_sudden_stop = any(marker in incident_desc for marker in sudden_stop_markers)
    if (has_occupants and has_intersection) or (has_occupants and has_sudden_stop):
        result["patterns_detected"].append("staged_accident_pattern_cluster")
        result["risk_factors"].append(
            "Staged accident pattern cluster (occupants + intersection/sudden-stop pattern)"
        )
        result["pattern_score"] += int(fraud_cfg.get("staged_pattern_score", 20))

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

    repo = ctx.repo if ctx else ClaimRepository()
    fraud_cfg = get_fraud_config()
    provider_names = _extract_provider_names(claim_data, repo)
    for provider_name in provider_names:
        try:
            provider_claims = repo.get_claims_by_provider_name(provider_name, limit=200)
        except Exception as e:
            logger.debug("Provider lookup failed for %s: %s", provider_name, e)
            continue
        suspicious = [
            row
            for row in provider_claims
            if _as_nonempty_str(row.get("status"))
            in {"needs_review", "fraud_suspected", "fraud_confirmed", "under_investigation"}
        ]
        if len(suspicious) >= int(fraud_cfg.get("provider_ring_threshold", 2)):
            result["database_matches"].append("provider_ring_suspected")
            result["recommendations"].append(
                f"Provider '{provider_name}' appears in {len(suspicious)} suspicious claims"
            )
            result["cross_reference_score"] += int(fraud_cfg.get("provider_ring_score", 20))
            break

    # ClaimSearch integration seam (NICB/ISO via adapter).
    search_terms = {
        "vin": _as_nonempty_str(claim_data.get("vin")),
        "claimant_name": _as_nonempty_str(claim_data.get("claimant_name")),
    }
    date_range: tuple[str, str] | None = None
    incident_dt = _coerce_date(claim_data.get("incident_date"))
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
