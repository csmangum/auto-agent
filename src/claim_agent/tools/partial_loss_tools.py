"""Partial loss workflow tools for repair shop assignment and parts ordering."""

from __future__ import annotations

from crewai.tools import tool

from claim_agent.tools.logic import (
    get_available_repair_shops_impl,
    assign_repair_shop_impl,
    get_parts_catalog_impl,
    create_parts_order_impl,
    calculate_repair_estimate_impl,
    generate_repair_authorization_impl,
)


@tool("Get Available Repair Shops")
def get_available_repair_shops(
    location: str | None = None,
    vehicle_make: str | None = None,
    network_type: str | None = None,
) -> str:
    """Get list of available repair shops, optionally filtered.

    Args:
        location: Optional location filter (city/state).
        vehicle_make: Optional vehicle make for specialty matching.
        network_type: Optional network type (preferred, premium, standard).

    Returns:
        JSON string with list of available repair shops sorted by rating.
    """
    return get_available_repair_shops_impl(
        location=location,
        vehicle_make=vehicle_make,
        network_type=network_type,
    )


@tool("Assign Repair Shop")
def assign_repair_shop(
    claim_id: str,
    shop_id: str,
    estimated_repair_days: int = 5,
) -> str:
    """Assign a repair shop to a partial loss claim.
    
    Args:
        claim_id: The claim ID to assign the shop to.
        shop_id: The repair shop ID to assign (e.g., SHOP-001).
        estimated_repair_days: Estimated days to complete the repair.
    
    Returns:
        JSON string with assignment confirmation, dates, and confirmation number.
    """
    return assign_repair_shop_impl(
        claim_id=claim_id,
        shop_id=shop_id,
        estimated_repair_days=estimated_repair_days,
    )


@tool("Get Parts Catalog")
def get_parts_catalog(
    damage_description: str,
    vehicle_make: str,
    part_type_preference: str = "aftermarket",
) -> str:
    """Get recommended parts from catalog based on damage description.
    
    Args:
        damage_description: Description of the damage to identify needed parts.
        vehicle_make: Vehicle manufacturer for compatibility check.
        part_type_preference: Preferred type: oem, aftermarket, or refurbished.
    
    Returns:
        JSON string with recommended parts, pricing, and availability.
    """
    return get_parts_catalog_impl(
        damage_description=damage_description,
        vehicle_make=vehicle_make,
        part_type_preference=part_type_preference,
    )


@tool("Create Parts Order")
def create_parts_order(
    claim_id: str,
    parts: list,
    shop_id: str | None = None,
) -> str:
    """Create a parts order for a partial loss repair claim.

    Args:
        claim_id: The claim ID for the order.
        parts: List of dicts with part_id, quantity, and part_type for each part.
        shop_id: Optional shop ID for delivery address.

    Returns:
        JSON string with order confirmation, tracking, and delivery estimate.
    """
    return create_parts_order_impl(
        claim_id=claim_id,
        parts=parts,
        shop_id=shop_id,
    )


@tool("Calculate Repair Estimate")
def calculate_repair_estimate(
    damage_description: str,
    vehicle_make: str,
    vehicle_year: int,
    policy_number: str,
    shop_id: str | None = None,
    part_type_preference: str = "aftermarket",
) -> str:
    """Calculate a complete repair estimate including parts and labor.

    Args:
        damage_description: Description of the damage.
        vehicle_make: Vehicle manufacturer.
        vehicle_year: Year of the vehicle.
        policy_number: Policy number for deductible lookup.
        shop_id: Optional shop ID for labor rate.
        part_type_preference: Preferred part type: oem, aftermarket, refurbished.

    Returns:
        JSON string with full estimate breakdown: parts, labor, deductible, insurance pays.
    """
    return calculate_repair_estimate_impl(
        damage_description=damage_description,
        vehicle_make=vehicle_make,
        vehicle_year=vehicle_year,
        policy_number=policy_number,
        shop_id=shop_id,
        part_type_preference=part_type_preference,
    )


@tool("Generate Repair Authorization")
def generate_repair_authorization(
    claim_id: str,
    shop_id: str,
    total_estimate: float,
    parts_cost: float,
    labor_cost: float,
    deductible: float,
    customer_pays: float,
    insurance_pays: float,
    customer_approved: bool = True,
) -> str:
    """Generate a repair authorization document for a partial loss claim.
    
    Args:
        claim_id: The claim ID.
        shop_id: The assigned repair shop ID.
        total_estimate: Total repair estimate amount.
        parts_cost: Authorized parts cost.
        labor_cost: Authorized labor cost.
        deductible: Policy deductible amount.
        customer_pays: Amount customer is responsible for.
        insurance_pays: Amount insurance will pay.
        customer_approved: Whether customer has approved the repair.
    
    Returns:
        JSON string with repair authorization details and terms.
    """
    repair_estimate = {
        "total_estimate": total_estimate,
        "parts_cost": parts_cost,
        "labor_cost": labor_cost,
        "deductible": deductible,
        "customer_pays": customer_pays,
        "insurance_pays": insurance_pays,
    }
    return generate_repair_authorization_impl(
        claim_id=claim_id,
        shop_id=shop_id,
        repair_estimate=repair_estimate,
        customer_approved=customer_approved,
    )
