"""Shared utility functions for fraud detection modules."""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from claim_agent.db.repository import ClaimRepository

logger = logging.getLogger(__name__)


def _as_nonempty_str(raw: Any) -> str:
    """Coerce value to non-empty trimmed string, or empty string."""
    return raw.strip() if isinstance(raw, str) else ""


def _coerce_date(raw: Any) -> datetime | None:
    """Coerce value to datetime. Accepts datetime, date, or ISO date string."""
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


def _extract_provider_names(claim_data: dict[str, Any], repo: ClaimRepository) -> list[str]:
    """Extract provider names from claim data and database parties.
    
    Searches claim payload for provider-related fields and queries the database
    for provider-type parties associated with the claim.
    """
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
