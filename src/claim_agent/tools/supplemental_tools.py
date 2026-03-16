"""Supplemental claim tools for additional damage discovered during repair.

When these tools are invoked by the supplemental crew, CrewAI passes only the
declared tool parameters (e.g. claim_id). No request-scoped ClaimContext is
available, so impls use the process-default database (ClaimRepository() with
env db_path) and adapters. The orchestrator still uses the injected ctx.repo
for writes. Multi-DB or per-request DB is not supported for crew-invoked tools.
"""

from __future__ import annotations

from crewai.tools import tool

from claim_agent.tools.partial_loss_logic import (
    calculate_supplemental_estimate_impl,
    get_original_repair_estimate_impl,
    update_repair_authorization_impl,
)


@tool("Get Original Repair Estimate")
def get_original_repair_estimate(claim_id: str) -> str:
    """Retrieve the original repair estimate from a partial loss claim's workflow.

    Use this when processing a supplemental claim to compare new damage to the
    original estimate and authorization.

    Args:
        claim_id: The claim ID to fetch the original estimate for.

    Returns:
        JSON string with total_estimate, parts_cost, labor_cost, authorization_id,
        shop_id, and related fields from the original partial loss workflow.
    """
    return get_original_repair_estimate_impl(claim_id=claim_id)


@tool("Calculate Supplemental Estimate")
def calculate_supplemental_estimate(
    supplemental_damage_description: str,
    vehicle_make: str,
    vehicle_year: int,
    policy_number: str,
    shop_id: str | None = None,
    part_type_preference: str = "aftermarket",
    loss_state: str | None = None,
) -> str:
    """Calculate repair estimate for supplemental (additional) damage only.

    Use when additional damage was discovered during repair. Estimates parts
    and labor for the new damage. Typically no additional deductible applies.
    Uses state-specific total loss threshold when loss_state is provided (use
    loss_state from claim_data when available).

    Args:
        supplemental_damage_description: Description of the newly discovered damage.
        vehicle_make: Vehicle manufacturer.
        vehicle_year: Year of the vehicle.
        policy_number: Policy number for the claim.
        shop_id: Optional shop ID for labor rate (use same shop as original).
        part_type_preference: Preferred part type: oem, aftermarket, refurbished.
        loss_state: State/jurisdiction where loss occurred (California, Texas, Florida, New York).

    Returns:
        JSON string with parts, labor, total_estimate for the supplemental damage.
    """
    return calculate_supplemental_estimate_impl(
        supplemental_damage_description=supplemental_damage_description,
        vehicle_make=vehicle_make,
        vehicle_year=vehicle_year,
        policy_number=policy_number,
        shop_id=shop_id,
        part_type_preference=part_type_preference,
        loss_state=loss_state,
    )


@tool("Update Repair Authorization")
def update_repair_authorization(
    claim_id: str,
    shop_id: str,
    original_total: float,
    original_parts: float,
    original_labor: float,
    original_insurance_pays: float,
    supplemental_total: float,
    supplemental_parts: float,
    supplemental_labor: float,
    supplemental_insurance_pays: float,
    authorization_id: str | None = None,
    customer_approved: bool = True,
) -> str:
    """Update repair authorization with supplemental amounts.

    Adds supplemental authorization to the original and returns combined totals.
    Use after validating supplemental damage and calculating the supplemental estimate.

    Args:
        claim_id: The claim ID.
        shop_id: The repair shop ID (same as original).
        original_total: Original total estimate.
        original_parts: Original parts cost.
        original_labor: Original labor cost.
        original_insurance_pays: Original insurance payment amount.
        supplemental_total: Supplemental total estimate.
        supplemental_parts: Supplemental parts cost.
        supplemental_labor: Supplemental labor cost.
        supplemental_insurance_pays: Supplemental insurance payment.
        authorization_id: Original authorization ID if known.
        customer_approved: Whether customer approved the supplemental.

    Returns:
        JSON string with combined totals and supplemental authorization details.
    """
    return update_repair_authorization_impl(
        claim_id=claim_id,
        shop_id=shop_id,
        original_total=original_total,
        original_parts=original_parts,
        original_labor=original_labor,
        original_insurance_pays=original_insurance_pays,
        supplemental_total=supplemental_total,
        supplemental_parts=supplemental_parts,
        supplemental_labor=supplemental_labor,
        supplemental_insurance_pays=supplemental_insurance_pays,
        authorization_id=authorization_id,
        customer_approved=customer_approved,
    )
