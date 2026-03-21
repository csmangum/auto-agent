"""Vehicle valuation and payout calculation logic."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from claim_agent.adapters.registry import get_gap_insurance_adapter, get_valuation_adapter
from claim_agent.config.settings import (
    DEFAULT_BASE_VALUE,
    DEPRECIATION_PER_YEAR,
    MIN_PAYOUT_VEHICLE_VALUE,
    MIN_VEHICLE_VALUE,
)
from claim_agent.compliance.diminished_value import compute_diminished_value_payload
from claim_agent.exceptions import AdapterError, DomainValidationError
from claim_agent.models.policy_lookup import PolicyLookupFailure, PolicyLookupSuccess
from claim_agent.tools.policy_logic import query_policy_db_impl

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)


def calculate_diminished_value_impl(
    vehicle_value: float,
    loss_state: str | None,
    *,
    mileage: int | None = None,
    vehicle_year: int | None = None,
    repair_cost: float | None = None,
    damage_severity_tier: str | None = None,
) -> str:
    """Calculate diminished value when state requires it (e.g. Georgia 17c-style).

    Georgia uses base cap (10% of ACV) × damage × mileage multipliers when
    ``diminished_value_formula`` is ``ga_17c``. Other required states use a
    generic percentage fallback until a formula is configured.

    Returns 0 when state does not require diminished value consideration.
    """
    return json.dumps(
        compute_diminished_value_payload(
            vehicle_value,
            loss_state,
            mileage=mileage,
            vehicle_year=vehicle_year,
            repair_cost=repair_cost,
            damage_severity_tier=damage_severity_tier,
        )
    )


def _mock_comparables_for_value(
    base_value: float, year: int, make: str, model: str
) -> list[dict]:
    """Generate 2 mock comparable vehicles within ±10% of base (deterministic)."""
    return [
        {
            "vin": f"EST{year}01{int(base_value) % 100000:05d}",
            "year": year,
            "make": make,
            "model": model,
            "price": round(base_value * 0.92, 2),
            "mileage": 45000,
            "source": "mock_estimated",
        },
        {
            "vin": f"EST{year}02{int(base_value) % 100000:05d}",
            "year": year,
            "make": make,
            "model": model,
            "price": round(base_value * 1.05, 2),
            "mileage": 32000,
            "source": "mock_estimated",
        },
    ]


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
        result = {
            "value": v.get("value", 15000),
            "condition": v.get("condition", "good"),
            "source": "mock_kbb",
        }
        if "comparables" in v and v["comparables"]:
            result["comparables"] = v["comparables"]
        return json.dumps(result)
    current_year = datetime.now().year
    default_value = max(
        MIN_VEHICLE_VALUE,
        DEFAULT_BASE_VALUE + (current_year - year_int) * -DEPRECIATION_PER_YEAR,
    )
    result = {
        "value": default_value,
        "condition": "good",
        "source": "mock_kbb_estimated",
    }
    # Attach mock comparables whenever adapter returns no valuation (e.g. for TL workflows).
    result["comparables"] = _mock_comparables_for_value(
        default_value, year_int, make or "Unknown", model or "Unknown"
    )
    return json.dumps(result)


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


# Approximate sales tax + DMV/registration fees by state (CA CIC 11580.26; varies by state)
_DEFAULT_SALES_TAX_PCT = 0.08
_DEFAULT_DMV_FEES = 150.0


def _coordinate_gap_shortfall(
    *,
    claim_id: str | None,
    policy_number: str,
    payout_amount: float,
    loan_balance: float,
    shortfall_amount: float,
    vin: str | None,
    ctx: ClaimContext | None,
) -> dict[str, object]:
    """Call gap carrier adapter; returned keys merge into calculate_payout JSON."""
    adapter = ctx.adapters.gap_insurance if ctx else get_gap_insurance_adapter()
    out: dict[str, object] = {
        "gap_shortfall_amount": round(shortfall_amount, 2),
    }
    try:
        submitted = adapter.submit_shortfall_claim(
            claim_id=claim_id or "",
            policy_number=policy_number,
            auto_payout_amount=payout_amount,
            loan_balance=loan_balance,
            shortfall_amount=shortfall_amount,
            vin=vin,
        )
    except NotImplementedError as e:
        logger.warning("Gap insurance adapter unavailable: %s", e)
        out["gap_coordination_error"] = (
            "Gap carrier integration not configured; manual coordination required."
        )
        return out
    except Exception:
        logger.exception("Gap insurance submission failed")
        out["gap_coordination_error"] = (
            "Gap carrier submission failed; manual coordination required."
        )
        return out

    out["gap_claim_id"] = submitted.get("gap_claim_id")
    out["gap_claim_status"] = submitted.get("status")
    if submitted.get("approved_amount") is not None:
        out["gap_approved_amount"] = submitted["approved_amount"]
    if submitted.get("denial_reason"):
        out["gap_denial_reason"] = submitted["denial_reason"]
    rem = submitted.get("remaining_shortfall_after_gap")
    if rem is not None:
        out["gap_remaining_shortfall"] = rem
    if submitted.get("message"):
        out["gap_carrier_message"] = submitted["message"]

    # Only poll the gap carrier when the initial submission response does not
    # provide all of the fields we care about. This avoids an extra network
    # call in cases where the submission already contains final status data.
    should_poll = any(
        key not in out or out[key] is None
        for key in (
            "gap_claim_status",
            "gap_approved_amount",
            "gap_denial_reason",
            "gap_remaining_shortfall",
        )
    )

    gap_ref = out.get("gap_claim_id")
    if isinstance(gap_ref, str) and gap_ref and should_poll:
        try:
            polled = adapter.get_claim_status(gap_ref)
        except NotImplementedError:
            polled = None
        except Exception as e:
            logger.warning("Gap insurance status poll failed for %s: %s", gap_ref, e)
            polled = None
        if polled:
            st = polled.get("status")
            if st:
                out["gap_claim_status"] = st
            if polled.get("approved_amount") is not None:
                out["gap_approved_amount"] = polled["approved_amount"]
            if polled.get("denial_reason"):
                out["gap_denial_reason"] = polled["denial_reason"]
            pr = polled.get("remaining_shortfall_after_gap")
            if pr is not None:
                out["gap_remaining_shortfall"] = pr

    return out


def _estimate_tax_title_fees(vehicle_value: float, loss_state: str | None) -> float:
    """Estimate tax, title, and registration fees for total loss replacement."""
    if not loss_state:
        return 0.0
    # State-specific rates (simplified; real implementation would use state rules)
    tax_pct = _DEFAULT_SALES_TAX_PCT
    dmv_fees = _DEFAULT_DMV_FEES
    return round(vehicle_value * tax_pct + dmv_fees, 2)


def calculate_payout_impl(
    vehicle_value: float,
    policy_number: str,
    *,
    damage_description: str = "",
    coverage_type: str | None = None,
    loss_state: str | None = None,
    tax_title_fees: float | None = None,
    owner_retain_salvage: bool = False,
    salvage_value: float | None = None,
    loan_balance: float | None = None,
    claim_id: str | None = None,
    vin: str | None = None,
    ctx: ClaimContext | None = None,
) -> str:
    """Calculate total loss payout.

    Supports tax/title/fees (state-required), owner-retained salvage deduction,
    and loss_state for state-specific estimation.
    """
    if not isinstance(vehicle_value, (int, float)) or vehicle_value < MIN_PAYOUT_VEHICLE_VALUE:
        return json.dumps({
            "error": f"Invalid vehicle value (minimum: ${MIN_PAYOUT_VEHICLE_VALUE})",
            "payout_amount": 0.0,
            "vehicle_value": vehicle_value,
            "deductible": 0,
            "calculation": f"Error: Vehicle value must be at least ${MIN_PAYOUT_VEHICLE_VALUE}"
        })

    acv_base = round(vehicle_value, 2)

    # Tax/title/fees: use provided value or estimate when loss_state given
    if tax_title_fees is not None and isinstance(tax_title_fees, (int, float)):
        ttf = round(float(tax_title_fees), 2)
    elif loss_state:
        ttf = _estimate_tax_title_fees(acv_base, loss_state)
    else:
        ttf = 0.0

    acv_total = round(acv_base + ttf, 2)

    # Owner-retained salvage deduction
    salvage_deduction = 0.0
    if (
        owner_retain_salvage
        and salvage_value is not None
        and isinstance(salvage_value, (int, float))
        and salvage_value > 0
    ):
        salvage_deduction = round(float(salvage_value), 2)

    try:
        policy = query_policy_db_impl(
            policy_number,
            damage_description=damage_description,
            coverage_type=coverage_type,
            ctx=ctx,
        )
    except (DomainValidationError, AdapterError) as e:
        return json.dumps({
            "error": str(e),
            "payout_amount": 0.0,
            "vehicle_value": acv_base,
            "deductible": 0,
            "calculation": "Error: Unable to retrieve policy information",
        })
    if isinstance(policy, PolicyLookupFailure):
        return json.dumps({
            "error": "Invalid or inactive policy",
            "payout_amount": 0.0,
            "vehicle_value": acv_base,
            "deductible": 0,
            "calculation": "Error: Policy not found or inactive",
        })
    policy_data: PolicyLookupSuccess = policy
    if not policy_data.physical_damage_covered:
        return json.dumps({
            "error": "Policy does not include applicable physical damage coverage",
            "payout_amount": 0.0,
            "vehicle_value": acv_base,
            "deductible": 0,
            "calculation": "Error: Collision/comprehensive coverage is required",
        })
    collision_deductible = policy_data.collision_deductible
    comprehensive_deductible = policy_data.comprehensive_deductible
    if (
        not coverage_type
        and not damage_description
        and collision_deductible is not None
        and comprehensive_deductible is not None
        and collision_deductible != comprehensive_deductible
    ):
        return json.dumps({
            "error": "Coverage context required for policy with different collision/comprehensive deductibles",
            "payout_amount": 0.0,
            "vehicle_value": acv_base,
            "deductible": 0,
            "calculation": "Error: Provide coverage_type ('collision' or 'comprehensive')",
        })
    deductible = policy_data.deductible

    payout_amount = max(0.0, acv_total - deductible - salvage_deduction)

    # Gap insurance: when payout < loan balance and policy has gap, flag and coordinate
    gap_insurance_applied = False
    gap_coordination: dict[str, object] = {}
    if (
        loan_balance is not None
        and isinstance(loan_balance, (int, float))
        and loan_balance > 0
        and payout_amount < loan_balance
    ):
        lb = float(loan_balance)
        gap_insurance = bool(policy_data.gap_insurance)
        if gap_insurance:
            gap_insurance_applied = True
            shortfall = max(0.0, round(lb - payout_amount, 2))
            vin_clean = vin.strip() if isinstance(vin, str) else None
            if vin_clean == "":
                vin_clean = None
            gap_coordination = _coordinate_gap_shortfall(
                claim_id=claim_id.strip() if isinstance(claim_id, str) and claim_id.strip() else None,
                policy_number=policy_number,
                payout_amount=payout_amount,
                loan_balance=lb,
                shortfall_amount=shortfall,
                vin=vin_clean,
                ctx=ctx,
            )

    calc_parts = [f"${acv_total:,.2f} (ACV"]
    if ttf > 0:
        calc_parts[0] += f" incl ${ttf:,.2f} tax/fees"
    calc_parts[0] += ")"
    calc_parts.append(f"- ${deductible:,.2f} (deductible)")
    if salvage_deduction > 0:
        calc_parts.append(f"- ${salvage_deduction:,.2f} (salvage deduction)")
    calc_parts.append(f"= ${payout_amount:,.2f}")

    result = {
        "payout_amount": round(payout_amount, 2),
        "vehicle_value": acv_base,
        "deductible": deductible,
        "calculation": " ".join(calc_parts),
        "acv_base": acv_base,
        "tax_title_fees": ttf if ttf > 0 else None,
        "acv_total": acv_total,
        "salvage_deduction": salvage_deduction if salvage_deduction > 0 else None,
        "owner_retain_option": owner_retain_salvage,
        "gap_insurance_applied": gap_insurance_applied,
    }
    if gap_coordination:
        result.update(gap_coordination)

    return json.dumps(result)
