"""Pluggable fraud indicator detectors.

Each detector is a function (claim_data, ctx) -> list[str] returning indicator codes.
Register detectors via register_fraud_detector(); run_fraud_detectors runs all.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable

from claim_agent.config.settings import get_escalation_config
from claim_agent.db.repository import ClaimRepository
from claim_agent.tools.valuation_logic import fetch_vehicle_value_impl

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)

# Registry of detector functions: (claim_data, ctx) -> list[str]
_FRAUD_DETECTORS: list[Callable[..., list[str]]] = []


def register_fraud_detector(detector: Callable[..., list[str]]) -> Callable[..., list[str]]:
    """Register a fraud indicator detector. Can be used as decorator."""
    _FRAUD_DETECTORS.append(detector)
    return detector


# ---------------------------------------------------------------------------
# Built-in detectors
# ---------------------------------------------------------------------------

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


@register_fraud_detector
def _detect_keyword_indicators(claim_data: dict, ctx: ClaimContext | None = None) -> list[str]:
    """Detect fraud indicators from staged/suspicious/timing/damage keywords in descriptions."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return indicators
    incident = (claim_data.get("incident_description") or "").strip().lower()
    damage = (claim_data.get("damage_description") or "").strip().lower()
    combined = f"{incident} {damage}"
    fraud_keywords = (
        KNOWN_FRAUD_PATTERNS["staged_accident_keywords"]
        + KNOWN_FRAUD_PATTERNS["suspicious_claim_keywords"]
        + KNOWN_FRAUD_PATTERNS["timing_red_flags"]
        + KNOWN_FRAUD_PATTERNS["damage_fraud_keywords"]
    )
    for kw in fraud_keywords:
        if kw in combined:
            indicators.append(kw.replace(" ", "_"))
    return indicators


@register_fraud_detector
def _detect_vin_history_indicators(claim_data: dict, ctx: ClaimContext | None = None) -> list[str]:
    """Detect multiple claims on same VIN within lookback window."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return indicators
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
    if not vin or not incident_date:
        return indicators
    try:
        repo = ctx.repo if ctx else ClaimRepository()
        dt_obj = datetime.strptime(incident_date, "%Y-%m-%d")
        start = (dt_obj - timedelta(days=get_escalation_config()["vin_claims_days"])).strftime("%Y-%m-%d")
        end = (dt_obj + timedelta(days=1)).strftime("%Y-%m-%d")
        matches = repo.search_claims(vin=vin, incident_date=None)
        same_vin = [m for m in matches if m.get("vin") == vin and m.get("incident_date") != incident_date]
        same_vin_in_window = [
            m
            for m in same_vin
            if (inc := m.get("incident_date")) is not None
            and isinstance(inc, str)
            and start <= inc <= end
        ]
        if len(same_vin_in_window) >= 1:
            indicators.append("multiple_claims_same_vin")
    except (ValueError, OSError) as e:
        logger.debug("VIN lookup skipped for fraud indicators: %s", e)
    return indicators


@register_fraud_detector
def _detect_damage_vs_value_indicators(claim_data: dict, ctx: ClaimContext | None = None) -> list[str]:
    """Detect damage near or above vehicle value."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return indicators
    estimated_damage = claim_data.get("estimated_damage")
    if isinstance(estimated_damage, str):
        try:
            estimated_damage = float(estimated_damage)
        except ValueError:
            estimated_damage = None
    if estimated_damage is None or not isinstance(estimated_damage, (int, float)) or estimated_damage <= 0:
        return indicators
    year = claim_data.get("vehicle_year")
    make = claim_data.get("make") or claim_data.get("vehicle_make") or ""
    model = claim_data.get("model") or claim_data.get("vehicle_model") or ""
    vin = (claim_data.get("vin") or "").strip()
    if not (year and make and model):
        return indicators
    val_res = fetch_vehicle_value_impl(vin, year, make, model, ctx=ctx)
    try:
        val_data = json.loads(val_res)
        vehicle_value = val_data.get("value")
        if isinstance(vehicle_value, (int, float)) and vehicle_value > 0:
            if estimated_damage >= get_escalation_config()["fraud_damage_vs_value_ratio"] * vehicle_value:
                indicators.append("damage_near_or_above_vehicle_value")
    except (json.JSONDecodeError, TypeError) as e:
        logger.debug("Vehicle value parse skipped for fraud indicators: %s", e)
    return indicators


def _compute_description_overlap(claim_data: dict) -> float | None:
    """Compute Jaccard overlap between incident and damage descriptions. Returns None if N/A."""
    if not claim_data or not isinstance(claim_data, dict):
        return None
    incident = (claim_data.get("incident_description") or "").strip().lower()
    damage = (claim_data.get("damage_description") or "").strip().lower()
    if not incident or not damage:
        return None
    words_i = _normalize_words_for_overlap(incident)
    words_d = _normalize_words_for_overlap(damage)
    if not words_i or not words_d:
        return None
    return len(words_i & words_d) / len(words_i | words_d) if (words_i | words_d) else 0


def get_description_overlap_evidence(claim_data: dict) -> dict | None:
    """Return {score, threshold} for incident/damage overlap. None if N/A.

    Used by get_escalation_evidence so the agent can reason over overlap
    without the rule directly deciding incident_damage_description_mismatch.
    """
    overlap = _compute_description_overlap(claim_data)
    if overlap is None:
        return None
    overlap_threshold = get_escalation_config()["description_overlap_threshold"]
    return {"score": round(overlap, 4), "threshold": overlap_threshold}


_OVERLAP_STOPWORDS = frozenset(
    {"a", "an", "and", "are", "at", "be", "been", "but", "did", "do", "does",
     "for", "had", "has", "have", "i", "in", "is", "may", "might", "my", "of",
     "on", "or", "our", "that", "the", "this", "to", "was", "were", "while",
     "will", "would"}
)


def _normalize_words_for_overlap(text: str) -> set[str]:
    """Normalize into content-word tokens: strip punctuation, split hyphens, drop stopwords."""
    tokens: set[str] = set()
    for raw in text.split():
        word = raw.strip(".,;:!?\"'()")
        if not word or word in _OVERLAP_STOPWORDS:
            continue
        for part in word.split("-"):
            if part and part not in _OVERLAP_STOPWORDS:
                tokens.add(part)
    return tokens


def _coerce_date(raw: Any) -> datetime | None:
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return datetime.combine(raw, datetime.min.time())
    if isinstance(raw, str):
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d")
        except ValueError:
            return None
    return None


def _as_nonempty_str(raw: Any) -> str:
    return raw.strip() if isinstance(raw, str) else ""


def _extract_provider_names(claim_data: dict) -> list[str]:
    names: list[str] = []
    candidate_fields = (
        "provider_name",
        "repair_shop_name",
        "medical_provider_name",
        "doctor_name",
        "body_shop_name",
    )
    for field in candidate_fields:
        value = claim_data.get(field)
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    list_fields = ("provider_names", "medical_providers", "repair_shops")
    for field in list_fields:
        value = claim_data.get(field)
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    names.append(item.strip())
                elif isinstance(item, dict):
                    for key in ("name", "provider_name", "shop_name"):
                        raw = item.get(key)
                        if isinstance(raw, str) and raw.strip():
                            names.append(raw.strip())
                            break
    return sorted(set(names))


@register_fraud_detector
def _detect_description_overlap_indicators(claim_data: dict, ctx: ClaimContext | None = None) -> list[str]:
    """Detect low overlap between incident and damage descriptions.

    Uses Jaccard similarity on normalized word sets (punctuation stripped, hyphenated
    words split) so semantically consistent pairs like "rear-ended" / "rear bumper"
    are not falsely flagged as description mismatch.
    """
    indicators: list[str] = []
    overlap = _compute_description_overlap(claim_data)
    if overlap is not None:
        overlap_threshold = get_escalation_config()["description_overlap_threshold"]
        if overlap < overlap_threshold:
            indicators.append("incident_damage_description_mismatch")
    return indicators


@register_fraud_detector
def _detect_velocity_indicators(claim_data: dict, ctx: ClaimContext | None = None) -> list[str]:
    """Detect high claim velocity from the same address across policies."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return indicators
    incident_dt = _coerce_date(claim_data.get("incident_date"))
    if incident_dt is None:
        return indicators

    velocity_days = get_escalation_config().get("vin_claims_days", 90)
    repo = ctx.repo if ctx else ClaimRepository()

    claim_id = _as_nonempty_str(claim_data.get("claim_id"))
    addresses: set[str] = set()
    for key in ("claimant_address", "policy_address", "garaging_address"):
        addr = _as_nonempty_str(claim_data.get(key))
        if addr:
            addresses.add(addr)
    if claim_id:
        try:
            parties = repo.get_claim_parties(claim_id)
            for party in parties:
                addr = _as_nonempty_str(party.get("address"))
                if addr:
                    addresses.add(addr)
        except Exception as e:
            logger.debug("Velocity detector failed to load parties for %s: %s", claim_id, e)

    if not addresses:
        return indicators

    try:
        for address in addresses:
            related = repo.get_claims_by_party_address(address, limit=50)
            in_window: list[dict[str, Any]] = []
            for related_claim in related:
                related_id = _as_nonempty_str(related_claim.get("id"))
                if claim_id and related_id == claim_id:
                    continue
                related_date = _coerce_date(related_claim.get("incident_date"))
                if related_date is None:
                    continue
                if abs((incident_dt - related_date).days) <= velocity_days:
                    in_window.append(related_claim)
            distinct_policies = {
                _as_nonempty_str(item.get("policy_number"))
                for item in in_window
                if _as_nonempty_str(item.get("policy_number"))
            }
            if len(in_window) >= 2 and len(distinct_policies) >= 2:
                indicators.append("high_velocity_same_address")
                break
    except Exception as e:
        logger.debug("Velocity detector skipped: %s", e)
    return indicators


@register_fraud_detector
def _detect_geographic_inconsistency_indicators(
    claim_data: dict, ctx: ClaimContext | None = None
) -> list[str]:
    """Detect state/jurisdiction inconsistencies between policy, loss, and repair location."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return indicators
    # Keep this detector resilient: only flag when we have at least two non-empty locations.
    policy_state = _as_nonempty_str(claim_data.get("policy_state"))
    loss_state = _as_nonempty_str(
        claim_data.get("loss_state") or claim_data.get("incident_state")
    )
    repair_state = _as_nonempty_str(claim_data.get("repair_shop_state"))
    nonempty = [s for s in (policy_state, loss_state, repair_state) if s]
    if len(nonempty) < 2:
        return indicators
    if len(set(nonempty)) > 1:
        indicators.append("geographic_state_inconsistency")
    return indicators


@register_fraud_detector
def _detect_provider_ring_indicators(claim_data: dict, ctx: ClaimContext | None = None) -> list[str]:
    """Detect recurring providers appearing across suspicious prior claims."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return indicators
    provider_names = _extract_provider_names(claim_data)
    if not provider_names:
        return indicators

    repo = ctx.repo if ctx else ClaimRepository()
    try:
        for provider_name in provider_names:
            related = repo.get_claims_by_provider_name(provider_name, limit=100)
            suspicious = [
                row for row in related
                if _as_nonempty_str(row.get("status"))
                in {"needs_review", "fraud_suspected", "fraud_confirmed", "under_investigation"}
            ]
            if len(suspicious) >= 2:
                indicators.append("provider_ring_suspected")
                break
    except Exception as e:
        logger.debug("Provider ring detector skipped: %s", e)
    return indicators


@register_fraud_detector
def _detect_staged_pattern_indicators(claim_data: dict, ctx: ClaimContext | None = None) -> list[str]:
    """Detect richer staged-accident patterns beyond basic keywords."""
    del ctx  # detector currently uses claim payload only
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return indicators
    incident = (claim_data.get("incident_description") or "").strip().lower()
    if not incident:
        return indicators
    occupant_markers = ("multiple occupants", "all passengers", "all injured", "whiplash")
    intersection_markers = ("intersection", "4-way", "four-way", "stop sign", "traffic light")
    sudden_stop_markers = ("sudden stop", "brake checked", "rear-ended at low speed")
    has_occupants = any(m in incident for m in occupant_markers)
    has_intersection = any(m in incident for m in intersection_markers)
    has_sudden_stop = any(m in incident for m in sudden_stop_markers)
    if (has_occupants and has_intersection) or (has_occupants and has_sudden_stop):
        indicators.append("staged_accident_pattern_cluster")
    return indicators


@register_fraud_detector
def _detect_relationship_graph_indicators(
    claim_data: dict, ctx: ClaimContext | None = None
) -> list[str]:
    """Detect dense relationship neighborhoods around claim parties/providers/VIN."""
    indicators: list[str] = []
    if not claim_data or not isinstance(claim_data, dict):
        return indicators
    repo = ctx.repo if ctx else ClaimRepository()
    claim_id = _as_nonempty_str(claim_data.get("claim_id"))
    if not claim_id:
        return indicators
    try:
        graph = repo.build_relationship_snapshot(claim_id=claim_id, max_depth=2, max_nodes=50)
        if graph.get("dense_cluster_detected") is True:
            indicators.append("relationship_graph_dense_cluster")
        if int(graph.get("high_risk_link_count", 0)) >= 2:
            indicators.append("relationship_graph_high_risk_links")
    except Exception as e:
        logger.debug("Relationship graph detector skipped: %s", e)
    return indicators


def run_fraud_detectors(claim_data: dict, ctx: ClaimContext | None = None) -> list[str]:
    """Run all registered fraud detectors and return combined unique indicators."""
    seen: set[str] = set()
    for detector in _FRAUD_DETECTORS:
        try:
            for ind in detector(claim_data, ctx):
                if ind and ind not in seen:
                    seen.add(ind)
        except Exception as e:
            logger.warning("Fraud detector %s failed: %s", detector.__name__, e)
    return sorted(seen)
