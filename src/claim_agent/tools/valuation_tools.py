"""Vehicle valuation tools (mock KBB-style API)."""

from crewai.tools import tool

from claim_agent.tools.valuation_logic import (
    calculate_diminished_value_impl,
    calculate_payout_impl,
    evaluate_damage_impl,
    fetch_vehicle_value_impl,
)


@tool("Fetch Vehicle Value")
def fetch_vehicle_value(vin: str, year: int, make: str, model: str) -> str:
    """Fetch current market value for a vehicle (mock KBB API).
    Use VIN if available; otherwise year/make/model.
    Args:
        vin: Vehicle identification number.
        year: Year of vehicle.
        make: Vehicle manufacturer.
        model: Vehicle model.
    Returns:
        JSON string with value (float), condition (str), and source (str).
    """
    return fetch_vehicle_value_impl(vin, year, make, model)


@tool("Calculate Diminished Value")
def calculate_diminished_value(
    vehicle_value: float,
    loss_state: str | None = None,
) -> str:
    """Calculate diminished value when state requires it (e.g. Georgia).

    Returns 0 when state does not require diminished value.
    Args:
        vehicle_value: ACV of the vehicle.
        loss_state: State/jurisdiction (Georgia mandates; most states do not).

    Returns:
        JSON with diminished_value, required, state, message.
    """
    return calculate_diminished_value_impl(vehicle_value, loss_state)


@tool("Evaluate Damage Severity")
def evaluate_damage(damage_description: str, estimated_repair_cost: float | None = None) -> str:
    """Evaluate damage description and optional repair cost to assess severity.
    Args:
        damage_description: Text description of vehicle damage.
        estimated_repair_cost: Optional estimated repair cost in dollars.
    Returns:
        JSON string with severity (str), estimated_repair_cost (float), total_loss_candidate (bool).
    """
    return evaluate_damage_impl(damage_description, estimated_repair_cost)


@tool("Calculate Payout")
def calculate_payout(
    vehicle_value: float,
    policy_number: str,
    damage_description: str = "",
    coverage_type: str | None = None,
    loss_state: str | None = None,
    tax_title_fees: float | None = None,
    owner_retain_salvage: bool = False,
    salvage_value: float | None = None,
    loan_balance: float | None = None,
) -> str:
    """Calculate total loss payout.

    Supports tax/title/fees (required in many states), owner-retained salvage
    deduction, and loss_state for state-specific estimation.
    Args:
        vehicle_value: Current market value (ACV base) of the vehicle in dollars.
        policy_number: Policy number to look up deductible amount.
        damage_description: Optional damage description to infer collision vs comprehensive.
        coverage_type: Optional explicit coverage type ("collision" or "comprehensive").
        loss_state: State/jurisdiction (California, Texas, Florida, New York) for tax/fees.
        tax_title_fees: Override estimated sales tax + DMV/registration fees.
        owner_retain_salvage: Whether policyholder retains the salvage vehicle.
        salvage_value: Salvage value to deduct when owner_retain_salvage is True.
        loan_balance: Optional loan balance; when payout < loan_balance and policy has
            gap_insurance, gap_insurance_applied is set True.
    Returns:
        JSON with payout_amount, vehicle_value, deductible, calculation, acv_base,
        tax_title_fees, acv_total, salvage_deduction, owner_retain_option.
    """
    return calculate_payout_impl(
        vehicle_value,
        policy_number,
        damage_description=damage_description,
        coverage_type=coverage_type,
        loss_state=loss_state,
        tax_title_fees=tax_title_fees,
        owner_retain_salvage=owner_retain_salvage,
        salvage_value=salvage_value,
        loan_balance=loan_balance,
    )
