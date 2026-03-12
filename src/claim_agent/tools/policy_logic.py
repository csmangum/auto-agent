"""Policy database lookup logic."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from claim_agent.adapters.registry import get_policy_adapter
from claim_agent.exceptions import AdapterError, DomainValidationError

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)


def _policy_coverage_summary(p: dict[str, Any]) -> str:
    """Return human-readable coverage summary. Supports coverages array or legacy coverage string."""
    coverages = p.get("coverages")
    if coverages and isinstance(coverages, list):
        return "+".join(str(c) for c in coverages)
    return p.get("coverage", "liability")


def _policy_physical_damage_deductible(p: dict[str, Any], damage_description: str = "") -> float:
    """Return deductible for collision/comprehensive claims based on damage type.
    
    Analyzes damage_description to determine whether this is a comprehensive claim
    (theft, vandalism, fire, weather, animal, glass, hail, flood) or a collision claim.
    Returns the appropriate deductible, or falls back to collision deductible if unknown.
    """
    coverages = p.get("coverages") or []
    collision_deductible = p.get("collision_deductible")
    comprehensive_deductible = p.get("comprehensive_deductible")
    
    # Comprehensive claim keywords (non-collision damage)
    comprehensive_keywords = {
        "theft", "stolen", "vandalism", "vandalized", "fire", "burned", "burning",
        "weather", "hail", "flood", "flooded", "water damage", "wind", "tornado",
        "hurricane", "animal", "deer", "glass", "windshield", "window"
    }
    
    # If we have damage description, analyze it to determine claim type
    if damage_description:
        damage_lower = damage_description.lower()
        is_comprehensive = any(keyword in damage_lower for keyword in comprehensive_keywords)
        
        # Return appropriate deductible based on damage type
        if is_comprehensive:
            if "comprehensive" in coverages and comprehensive_deductible is not None:
                return float(comprehensive_deductible)
            if comprehensive_deductible is not None:
                return float(comprehensive_deductible)
        else:
            # Collision claim
            if "collision" in coverages and collision_deductible is not None:
                return float(collision_deductible)
            if collision_deductible is not None:
                return float(collision_deductible)
    
    # Fallback logic when no damage description or both deductibles available
    if "collision" in coverages and collision_deductible is not None:
        return float(collision_deductible)
    if "comprehensive" in coverages and comprehensive_deductible is not None:
        return float(comprehensive_deductible)
    if collision_deductible is not None:
        return float(collision_deductible)
    if comprehensive_deductible is not None:
        return float(comprehensive_deductible)
    return float(p.get("deductible", 500))


def query_policy_db_impl(
    policy_number: str,
    *,
    damage_description: str = "",
    ctx: ClaimContext | None = None,
) -> str:
    if not policy_number or not isinstance(policy_number, str):
        raise DomainValidationError("Invalid policy number")
    policy_number = policy_number.strip()
    if not policy_number:
        raise DomainValidationError("Empty policy number")
    adapter = ctx.adapters.policy if ctx else get_policy_adapter()
    try:
        p = adapter.get_policy(policy_number)
    except NotImplementedError as exc:
        logger.warning("Policy adapter get_policy not implemented: %s", exc)
        raise AdapterError("Policy lookup is not supported by the configured adapter") from exc
    except Exception as exc:
        logger.exception("Unexpected error while querying policy adapter")
        raise AdapterError("Error querying policy database") from exc
    if p is not None:
        status = p.get("status", "active")
        is_active = isinstance(status, str) and status.lower() == "active"
        if is_active:
            result = {
                "valid": True,
                "coverage": _policy_coverage_summary(p),
                "deductible": _policy_physical_damage_deductible(p, damage_description),
                "status": status,
            }
            rental = p.get("rental_reimbursement") or p.get("transportation_expenses")
            if rental and isinstance(rental, dict):
                result["rental_reimbursement"] = rental
            return json.dumps(result)
        return json.dumps({
            "valid": False,
            "status": status,
            "message": "Policy not found or inactive",
        })
    return json.dumps({"valid": False, "message": "Policy not found or inactive"})
