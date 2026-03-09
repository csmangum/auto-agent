"""Salvage tools: get salvage value, initiate title transfer, record disposition."""

from crewai.tools import tool

from claim_agent.tools.salvage_logic import (
    get_salvage_value_impl,
    initiate_title_transfer_impl,
    record_salvage_disposition_impl,
)


@tool("Get Salvage Value")
def get_salvage_value(
    vin: str,
    vehicle_year: int,
    make: str,
    model: str,
    damage_description: str = "",
    vehicle_value: float | None = None,
) -> str:
    """Estimate salvage value from vehicle data and damage description.

    Use vehicle_value from workflow when available; otherwise an estimate is used.
    Salvage is typically 15-25% of ACV depending on damage severity (flood/fire lower).

    Args:
        vin: Vehicle identification number.
        vehicle_year: Year of vehicle.
        make: Vehicle manufacturer.
        model: Vehicle model.
        damage_description: Description of vehicle damage.
        vehicle_value: Optional ACV from workflow (use when available).

    Returns:
        JSON with salvage_value, vehicle_value_used, salvage_pct,
        disposition_recommendation (auction|owner_retention|scrap), reasoning.
    """
    return get_salvage_value_impl(
        vin=vin,
        vehicle_year=vehicle_year,
        make=make,
        model=model,
        damage_description=damage_description or "",
        vehicle_value=vehicle_value,
    )


@tool("Initiate Title Transfer")
def initiate_title_transfer(
    claim_id: str,
    vin: str,
    vehicle_year: int,
    make: str,
    model: str,
    disposition_type: str,
) -> str:
    """Initiate DMV title transfer or salvage certificate for total loss vehicle.

    Args:
        claim_id: The claim ID.
        vin: Vehicle identification number.
        vehicle_year: Year of vehicle.
        make: Vehicle manufacturer.
        model: Vehicle model.
        disposition_type: auction, owner_retention, or scrap.

    Returns:
        JSON with transfer_id, status, dmv_reference, initiated_at.
    """
    return initiate_title_transfer_impl(
        claim_id=claim_id,
        vin=vin,
        vehicle_year=vehicle_year,
        make=make,
        model=model,
        disposition_type=disposition_type,
    )


@tool("Record Salvage Disposition")
def record_salvage_disposition(
    claim_id: str,
    disposition_type: str,
    salvage_amount: float | None = None,
    status: str = "pending",
    notes: str = "",
) -> str:
    """Record salvage disposition outcome and auction/recovery status.

    Args:
        claim_id: The claim ID.
        disposition_type: auction, owner_retention, or scrap.
        salvage_amount: Amount recovered from salvage (if any).
        status: pending, auction_scheduled, auction_complete, owner_retained, or scrapped.
        notes: Optional notes about disposition.

    Returns:
        JSON with recorded disposition details.
    """
    return record_salvage_disposition_impl(
        claim_id=claim_id,
        disposition_type=disposition_type,
        salvage_amount=salvage_amount,
        status=status,
        notes=notes or "",
    )
