"""Vehicle valuation and payout calculation logic."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from claim_agent.adapters.registry import get_valuation_adapter
from claim_agent.config.settings import (
    DEFAULT_BASE_VALUE,
    DEFAULT_DEDUCTIBLE,
    DEPRECIATION_PER_YEAR,
    MIN_PAYOUT_VEHICLE_VALUE,
    MIN_VEHICLE_VALUE,
)
from claim_agent.exceptions import AdapterError, DomainValidationError
from claim_agent.tools.policy_logic import query_policy_db_impl

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)


def fetch_vehicle_value_impl(
    vin: str,
    year: int,
    make: str,
    model: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    vin = vin.strip() if isinstance(vin, str) else ""
    make = make.strip() if isinstance(make, str) else ""
    model = model.strip() if isinstance(model, str) else ""
    year_int = int(year) if isinstance(year, (int, float)) and year > 0 else 2020
    adapter = ctx.adapters.valuation if ctx else get_valuation_adapter()
    try:
        v = adapter.get_vehicle_value(vin, year_int, make, model)
    except NotImplementedError:
        logger.warning(
            "Valuation adapter is not implemented; falling back to default vehicle value",
        )
        v = None
    if v is not None:
        return json.dumps({
            "value": v.get("value", 15000),
            "condition": v.get("condition", "good"),
            "source": "mock_kbb",
        })
    current_year = datetime.now().year
    default_value = max(
        MIN_VEHICLE_VALUE,
        DEFAULT_BASE_VALUE + (current_year - year_int) * -DEPRECIATION_PER_YEAR,
    )
    return json.dumps({
        "value": default_value,
        "condition": "good",
        "source": "mock_kbb_estimated",
    })


def evaluate_damage_impl(damage_description: str, estimated_repair_cost: float | None) -> str:
    if not damage_description or not isinstance(damage_description, str):
        return json.dumps({
            "severity": "unknown",
            "estimated_repair_cost": estimated_repair_cost if estimated_repair_cost is not None else 0.0,
            "total_loss_candidate": False,
        })
    desc_lower = damage_description.strip().lower()
    if not desc_lower:
        return json.dumps({
            "severity": "unknown",
            "estimated_repair_cost": estimated_repair_cost if estimated_repair_cost is not None else 0.0,
            "total_loss_candidate": False,
        })
    total_loss_keywords = ["totaled", "total loss", "destroyed", "flood", "fire", "frame"]
    is_total_loss_candidate = any(k in desc_lower for k in total_loss_keywords)
    cost = estimated_repair_cost if estimated_repair_cost is not None else 0.0
    return json.dumps({
        "severity": "high" if is_total_loss_candidate else "medium",
        "estimated_repair_cost": cost,
        "total_loss_candidate": is_total_loss_candidate,
    })


def calculate_payout_impl(
    vehicle_value: float,
    policy_number: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Calculate total loss payout by subtracting deductible from vehicle value."""
    if not isinstance(vehicle_value, (int, float)) or vehicle_value < MIN_PAYOUT_VEHICLE_VALUE:
        return json.dumps({
            "error": f"Invalid vehicle value (minimum: ${MIN_PAYOUT_VEHICLE_VALUE})",
            "payout_amount": 0.0,
            "vehicle_value": vehicle_value,
            "deductible": 0,
            "calculation": f"Error: Vehicle value must be at least ${MIN_PAYOUT_VEHICLE_VALUE}"
        })

    vehicle_value = round(vehicle_value, 2)

    try:
        policy_result = query_policy_db_impl(policy_number, ctx=ctx)
    except (DomainValidationError, AdapterError) as e:
        return json.dumps({
            "error": str(e),
            "payout_amount": 0.0,
            "vehicle_value": vehicle_value,
            "deductible": 0,
            "calculation": "Error: Unable to retrieve policy information",
        })
    try:
        policy_data = json.loads(policy_result)
        if not policy_data.get("valid", False):
            return json.dumps({
                "error": "Invalid or inactive policy",
                "payout_amount": 0.0,
                "vehicle_value": vehicle_value,
                "deductible": 0,
                "calculation": "Error: Policy not found or inactive"
            })
        deductible = policy_data.get("deductible", DEFAULT_DEDUCTIBLE)
    except (json.JSONDecodeError, KeyError) as e:
        logger.error(
            "Policy lookup failed: %s",
            e,
            exc_info=True,
            extra={"extra_data": {"policy_number": policy_number, "error": str(e)}},
        )
        return json.dumps({
            "error": "Policy lookup failed. Please try again.",
            "payout_amount": 0.0,
            "vehicle_value": vehicle_value,
            "deductible": 0,
            "calculation": "Error: Unable to retrieve policy information"
        })

    payout_amount = max(0.0, vehicle_value - deductible)

    result = {
        "payout_amount": round(payout_amount, 2),
        "vehicle_value": vehicle_value,
        "deductible": deductible,
        "calculation": f"${vehicle_value:,.2f} (vehicle value) - ${deductible:,.2f} (deductible) = ${payout_amount:,.2f}"
    }

    return json.dumps(result)
