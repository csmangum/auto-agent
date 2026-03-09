"""Salvage logic: value estimation, title transfer, disposition recording."""

from __future__ import annotations

import datetime
import json
import logging


logger = logging.getLogger(__name__)


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# Salvage value as percentage of ACV by damage type (higher damage = lower salvage)
_SALVAGE_PCT_HIGH_DAMAGE = 0.15  # flood, fire, frame
_SALVAGE_PCT_MEDIUM_DAMAGE = 0.20  # collision, rollover
_SALVAGE_PCT_LOW_DAMAGE = 0.25  # minor total loss


def get_salvage_value_impl(
    vin: str,
    vehicle_year: int,
    make: str,
    model: str,
    damage_description: str = "",
    vehicle_value: float | None = None,
) -> str:
    """Estimate salvage value from vehicle data and damage.

    Uses vehicle_value when provided; otherwise estimates ACV from vehicle year and applies a damage-based salvage percentage.
    Salvage is typically 15-25% of ACV depending on damage severity.

    Returns JSON with:
    - salvage_value: float
    - vehicle_value_used: float
    - salvage_pct: float
    - disposition_recommendation: "auction" | "owner_retention" | "scrap"
    - reasoning: str
    """
    make = (make or "").strip()
    model = (model or "").strip()
    year_int = int(vehicle_year) if vehicle_year else 2020
    desc_lower = (damage_description or "").strip().lower()

    # Determine salvage percentage from damage type
    if any(kw in desc_lower for kw in ["flood", "fire", "submerged", "burned", "frame"]):
        pct = _SALVAGE_PCT_HIGH_DAMAGE
        reasoning = "High-severity damage (flood/fire/frame) reduces salvage value."
    elif any(kw in desc_lower for kw in ["totaled", "rollover", "collision", "destroyed"]):
        pct = _SALVAGE_PCT_MEDIUM_DAMAGE
        reasoning = "Moderate damage; typical salvage recovery for collision total loss."
    else:
        pct = _SALVAGE_PCT_LOW_DAMAGE
        reasoning = "Lower damage severity; higher salvage recovery potential."

    # Use provided vehicle_value or default estimate
    if vehicle_value is not None and isinstance(vehicle_value, (int, float)) and vehicle_value > 0:
        acv = float(vehicle_value)
        source = "workflow"
    else:
        current_year = _utc_now().year
        acv = max(5000, 15000 - (current_year - year_int) * 800)
        source = "estimated"

    salvage_value = round(acv * pct, 2)

    # Recommend disposition: scrap if very low value, owner_retention if policyholder may want
    if salvage_value < 500:
        disposition = "scrap"
        reasoning += " Very low salvage value; recommend scrap disposition."
    elif "owner" in desc_lower or "retain" in desc_lower:
        disposition = "owner_retention"
        reasoning += " Policyholder retention indicated; document salvage deduction."
    else:
        disposition = "auction"
        reasoning += " Auction recommended for standard total loss disposition."

    result = {
        "salvage_value": salvage_value,
        "vehicle_value_used": round(acv, 2),
        "salvage_pct": round(pct * 100, 1),
        "disposition_recommendation": disposition,
        "reasoning": reasoning,
        "source": source,
    }
    return json.dumps(result)


def initiate_title_transfer_impl(
    claim_id: str,
    vin: str,
    vehicle_year: int,
    make: str,
    model: str,
    disposition_type: str,
) -> str:
    """Initiate DMV title transfer or salvage certificate (mock implementation).

    disposition_type: auction | owner_retention | scrap

    Returns JSON with transfer_id, status, dmv_reference.
    """
    valid_types = ("auction", "owner_retention", "scrap")
    if disposition_type not in valid_types:
        logger.warning(
            "Invalid disposition_type %r, defaulting to auction",
            disposition_type,
        )
        disposition_type = "auction"

    transfer_id = f"SALV-{claim_id or 'UNK'}-{_utc_now().strftime('%Y%m%d%H')}"
    dmv_ref = f"DMV-{vin[:8] if vin else 'N/A'}-{_utc_now().strftime('%Y%m%d')}"

    result = {
        "transfer_id": transfer_id,
        "claim_id": claim_id,
        "vin": vin or "",
        "vehicle_year": vehicle_year,
        "make": make or "",
        "model": model or "",
        "disposition_type": disposition_type,
        "dmv_reference": dmv_ref,
        "status": "initiated",
        "initiated_at": _utc_now().isoformat().replace("+00:00", "Z"),
        "message": f"Title transfer initiated for {disposition_type} disposition.",
    }
    return json.dumps(result)


def record_salvage_disposition_impl(
    claim_id: str,
    disposition_type: str,
    salvage_amount: float | None = None,
    status: str = "pending",
    notes: str = "",
) -> str:
    """Record salvage disposition outcome and auction/recovery status (mock implementation).

    status: pending | auction_scheduled | auction_complete | owner_retained | scrapped
    """
    valid_statuses = ("pending", "auction_scheduled", "auction_complete", "owner_retained", "scrapped")
    if status not in valid_statuses:
        logger.warning(
            "Invalid status %r, defaulting to pending",
            status,
        )
        status = "pending"

    valid_types = ("auction", "owner_retention", "scrap")
    if disposition_type not in valid_types:
        logger.warning(
            "Invalid disposition_type %r, defaulting to auction",
            disposition_type,
        )
        disposition_type = "auction"

    result = {
        "claim_id": claim_id,
        "disposition_type": disposition_type,
        "salvage_amount": salvage_amount,
        "status": status,
        "notes": notes or "",
        "recorded_at": _utc_now().isoformat().replace("+00:00", "Z"),
        "message": "Salvage disposition recorded.",
    }
    return json.dumps(result)
