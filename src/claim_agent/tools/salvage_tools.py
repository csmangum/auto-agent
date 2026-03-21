"""Salvage tools: get salvage value, initiate title transfer, record disposition."""

from crewai.tools import tool

from claim_agent.tools.salvage_logic import (
    get_salvage_value_impl,
    initiate_title_transfer_impl,
    record_dmv_salvage_report_impl,
    record_salvage_disposition_impl,
    submit_nmvtis_report_impl,
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


@tool("Record DMV Salvage Report")
def record_dmv_salvage_report(
    claim_id: str,
    dmv_reference: str,
    salvage_title_status: str = "dmv_reported",
) -> str:
    """Record that salvage title was reported to state DMV.

    Call after initiate_title_transfer to persist dmv_reference and status
    on the claim for salvage title tracking.
    Args:
        claim_id: The claim ID.
        dmv_reference: DMV reference number from title transfer.
        salvage_title_status: pending, dmv_reported, or certificate_issued.

    Returns:
        JSON with recorded DMV report details on success. On validation error or
        if the claim does not exist, JSON with ``error`` (message string) and
        ``claim_id`` only.
    """
    return record_dmv_salvage_report_impl(
        claim_id=claim_id,
        dmv_reference=dmv_reference,
        salvage_title_status=salvage_title_status,
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


@tool("Submit NMVTIS Report")
def submit_nmvtis_report(claim_id: str, force_resubmit: bool = False) -> str:
    """Manually trigger or retry federal NMVTIS total-loss / salvage reporting.

    Normally runs automatically after DMV salvage reporting or final salvage disposition.
    Use when a prior submission failed (nmvtis_status=failed) or operations must resubmit.

    Args:
        claim_id: Claim identifier.
        force_resubmit: If True, submit again even when a prior submission was accepted.

    Returns:
        JSON with nmvtis_reference / nmvtis_status or error details.
    """
    return submit_nmvtis_report_impl(claim_id, force_resubmit=force_resubmit)
