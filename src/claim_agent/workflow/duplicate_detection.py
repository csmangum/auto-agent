"""Duplicate claim detection: VIN search, damage tag extraction, similarity scoring."""

import re
from datetime import date, datetime

from claim_agent.db.repository import ClaimRepository
from claim_agent.observability import get_logger
from claim_agent.workflow.claim_analysis import _has_catastrophic_event_keywords

logger = get_logger(__name__)

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


def _check_for_duplicates(claim_data: dict, current_claim_id: str | None = None) -> list[dict]:
    """Search for existing claims with same VIN and similar incident date.

    Returns list of potential duplicate claims (excluding the current claim if provided).
    """
    vin = claim_data.get("vin", "").strip()
    incident_date_raw = claim_data.get("incident_date")
    if isinstance(incident_date_raw, date):
        incident_date = incident_date_raw.isoformat()
    elif isinstance(incident_date_raw, str):
        incident_date = incident_date_raw.strip()
    else:
        incident_date = ""

    if not vin:
        return []

    repo = ClaimRepository()
    matches = repo.search_claims(vin=vin, incident_date=None)

    if current_claim_id:
        matches = [m for m in matches if m.get("id") != current_claim_id]

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
            matches.sort(key=lambda x: x.get("days_difference", 999))
        except (ValueError, TypeError) as exc:
            logger.warning(
                "Skipping incident date proximity ranking due to invalid incident_date format: %s",
                incident_date,
                exc_info=exc,
            )

    return matches
