"""Vehicle valuation tools (mock KBB-style API)."""

from crewai.tools import tool

from claim_agent.tools.logic import fetch_vehicle_value_impl, evaluate_damage_impl


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
