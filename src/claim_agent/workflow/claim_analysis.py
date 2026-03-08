"""Claim-level analysis: economic total loss, catastrophic event detection, keyword matching."""

import json
import re

from claim_agent.observability import get_logger

logger = get_logger(__name__)

_CATASTROPHIC_EVENT_KEYWORDS = [
    "flood", "flooded", "flooding", "fire", "fires", "submerged", "rollover", "rolled over",
    "roof crushed", "burned", "burning", "burnt",
]

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
    return any(re.search(r'\b' + re.escape(kw) + r'\b', text_lower) for kw in _CATASTROPHIC_EVENT_KEYWORDS)


def _has_explicit_total_loss_keywords(text: str) -> bool:
    """Check if text explicitly mentions total loss (totaled, destroyed, beyond repair, etc.)."""
    if not text:
        return False
    text_lower = text.lower()
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
    from claim_agent.tools.valuation_logic import fetch_vehicle_value_impl
    from claim_agent.config.settings import PARTIAL_LOSS_THRESHOLD

    damage_desc = claim_data.get("damage_description", "") or ""
    incident_desc = claim_data.get("incident_description", "") or ""

    is_catastrophic = _has_catastrophic_event_keywords(incident_desc) or _has_catastrophic_event_keywords(damage_desc)
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

    if cost_exceeds_threshold and damage_is_repairable and ratio < 1.0:
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
