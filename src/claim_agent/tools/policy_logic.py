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


def _normalized_coverages(p: dict[str, Any]) -> set[str]:
    """Return normalized coverage set from new or legacy policy formats."""
    coverages = p.get("coverages")
    if isinstance(coverages, list):
        return {
            str(coverage).strip().lower()
            for coverage in coverages
            if str(coverage).strip()
        }

    legacy_coverage = str(p.get("coverage", "")).strip().lower()
    if legacy_coverage in {"full_coverage", "full"}:
        return {"liability", "collision", "comprehensive"}
    if legacy_coverage:
        return {legacy_coverage}
    return set()


def _infer_physical_damage_coverage(damage_description: str) -> str | None:
    """Infer coverage type from freeform damage description when possible."""
    if not damage_description:
        return None

    damage_lower = damage_description.lower()
    comprehensive_keywords = {
        "theft", "stolen", "vandalism", "vandalized", "fire", "burned", "burning",
        "weather", "hail", "flood", "flooded", "water damage", "wind", "tornado",
        "hurricane", "animal", "deer", "glass", "windshield", "window",
    }
    if any(keyword in damage_lower for keyword in comprehensive_keywords):
        return "comprehensive"
    return "collision"


def _policy_coverage_summary(p: dict[str, Any]) -> str:
    """Return human-readable coverage summary. Supports coverages array or legacy coverage string."""
    normalized = _normalized_coverages(p)
    if normalized:
        return "+".join(sorted(normalized))
    return "liability"


def _policy_physical_damage_deductible(
    p: dict[str, Any],
    damage_description: str = "",
    *,
    coverage_type: str | None = None,
) -> float:
    """Return deductible for collision/comprehensive claims based on damage type.

    Analyzes damage_description to determine whether this is a comprehensive claim
    (theft, vandalism, fire, weather, animal, glass, hail, flood) or a collision claim.
    Returns the appropriate deductible, or falls back to collision deductible if unknown.
    """
    coverages = _normalized_coverages(p)
    collision_deductible = p.get("collision_deductible")
    comprehensive_deductible = p.get("comprehensive_deductible")

    selected_coverage = (
        str(coverage_type).strip().lower()
        if isinstance(coverage_type, str) and coverage_type.strip()
        else _infer_physical_damage_coverage(damage_description)
    )
    if selected_coverage == "comprehensive":
        if comprehensive_deductible is not None:
            return float(comprehensive_deductible)
    elif selected_coverage == "collision":
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
    if not any(coverage in coverages for coverage in ("collision", "comprehensive")):
        return 0.0
    return float(p.get("deductible", 500))


def _has_physical_damage_coverage(p: dict[str, Any], coverage_type: str | None = None) -> bool:
    """Return whether policy has applicable physical-damage coverage."""
    coverages = _normalized_coverages(p)
    selected_coverage = (
        str(coverage_type).strip().lower()
        if isinstance(coverage_type, str) and coverage_type.strip()
        else None
    )
    if selected_coverage in {"collision", "comprehensive"}:
        return selected_coverage in coverages
    return any(coverage in coverages for coverage in ("collision", "comprehensive"))


def query_policy_db_impl(
    policy_number: str,
    *,
    damage_description: str = "",
    coverage_type: str | None = None,
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
            coverages = _normalized_coverages(p)
            result = {
                "valid": True,
                "coverage": _policy_coverage_summary(p),
                "deductible": _policy_physical_damage_deductible(
                    p,
                    damage_description,
                    coverage_type=coverage_type,
                ),
                "status": status,
                "physical_damage_covered": _has_physical_damage_coverage(
                    p,
                    coverage_type=coverage_type,
                ),
                "physical_damage_coverages": sorted(
                    coverage
                    for coverage in coverages
                    if coverage in {"collision", "comprehensive"}
                ),
            }
            if p.get("collision_deductible") is not None:
                result["collision_deductible"] = float(p["collision_deductible"])
            if p.get("comprehensive_deductible") is not None:
                result["comprehensive_deductible"] = float(p["comprehensive_deductible"])
            if p.get("gap_insurance") is not None:
                result["gap_insurance"] = bool(p["gap_insurance"])
            rental = p.get("rental_reimbursement") or p.get("transportation_expenses")
            if rental and isinstance(rental, dict):
                result["rental_reimbursement"] = rental
            if p.get("named_insured") is not None:
                # Mask PII: retain only name for LLM/tool consumers; email/phone stripped.
                result["named_insured"] = [
                    {"name": entry["name"]}
                    for entry in p["named_insured"]
                    if isinstance(entry, dict) and isinstance(entry.get("name"), str)
                ]
            if p.get("drivers") is not None:
                # Mask PII: retain only name and relationship; license_number stripped.
                result["drivers"] = [
                    {"name": entry.get("name"), "relationship": entry.get("relationship")}
                    for entry in p["drivers"]
                    if isinstance(entry, dict) and isinstance(entry.get("name"), str)
                ]
            return json.dumps(result)
        return json.dumps({
            "valid": False,
            "status": status,
            "message": "Policy not found or inactive",
        })
    return json.dumps({"valid": False, "message": "Policy not found or inactive"})
