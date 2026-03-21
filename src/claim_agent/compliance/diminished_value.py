"""State-specific diminished value (DV) calculations.

Georgia first-party repairable-vehicle claims commonly apply the **17c** methodology
(Georgia Office of the Insurance Commissioner guidance; industry worksheet). This module
implements a transparent, versioned approximation suitable for workflow estimates — not
appraisal or legal advice.

Formula (Georgia 17c style):

    DV = base_value_loss × damage_multiplier × mileage_multiplier

where ``base_value_loss = 10% × pre-accident fair market value (ACV)`` (the statutory-style
cap used on the worksheet), and multipliers come from published bracket tables.
"""

from __future__ import annotations

import math
from typing import Any, Literal

from claim_agent.compliance.state_rules import get_state_rules

DamageBasis = Literal["repair_ratio", "tier", "default_assumption", "none"]


def _mileage_multiplier(mileage: int | None) -> float:
    """NADA-style mileage brackets used on Georgia 17c worksheets."""
    if mileage is None:
        return 1.0

    # Be tolerant of non-numeric inputs (e.g., strings from JSON/tooling).
    # If normalization fails, default to no mileage-based reduction.
    if not isinstance(mileage, (int, float)):
        try:
            mileage = int(mileage)  # type: ignore[assignment]
        except (TypeError, ValueError):
            return 1.0

    if mileage < 0:
        return 1.0
    if mileage < 20_000:
        return 1.0
    if mileage < 40_000:
        return 0.95
    if mileage < 60_000:
        return 0.90
    if mileage < 80_000:
        return 0.85
    if mileage < 100_000:
        return 0.80
    if mileage < 120_000:
        return 0.75
    return 0.70


def _damage_multiplier_from_repair_ratio(ratio: float) -> float:
    """Damage severity multiplier from repair cost ÷ FMV (17c worksheet brackets)."""
    if ratio < 0.20:
        return 0.0
    if ratio < 0.40:
        return 0.10
    if ratio < 0.60:
        return 0.20
    if ratio < 0.80:
        return 0.40
    if ratio < 0.95:
        return 0.60
    return 1.0


def _damage_multiplier_from_tier(tier: str) -> float:
    """Map qualitative repair tiers when itemized repair cost is unavailable."""
    t = tier.strip().lower().replace(" ", "_")
    mapping = {
        "cosmetic": 0.10,
        "light": 0.10,
        "moderate": 0.40,
        "major": 0.60,
        "structural": 0.80,
        "severe": 1.00,
    }
    return mapping.get(t, 0.40)


def _resolve_damage_multiplier(
    fmv: float,
    repair_cost: float | None,
    damage_severity_tier: str | None,
) -> tuple[float, DamageBasis, float | None]:
    if fmv <= 0:
        return 0.0, "none", None

    if repair_cost is not None and isinstance(repair_cost, (int, float)) and repair_cost >= 0:
        rc = float(repair_cost)
        ratio = rc / fmv
        return _damage_multiplier_from_repair_ratio(ratio), "repair_ratio", ratio

    if damage_severity_tier and str(damage_severity_tier).strip():
        return _damage_multiplier_from_tier(str(damage_severity_tier)), "tier", None

    return 0.40, "default_assumption", None


def calculate_ga_17c_diminished_value(
    fmv: float,
    *,
    mileage: int | None = None,
    repair_cost: float | None = None,
    damage_severity_tier: str | None = None,
) -> dict[str, Any]:
    """Return diminished value and multiplier breakdown for Georgia 17c-style estimate."""
    if not isinstance(fmv, (int, float)) or not math.isfinite(fmv) or fmv <= 0:
        return {
            "diminished_value": 0.0,
            "required": True,
            "state": "Georgia",
            "formula": "ga_17c",
            "error": "vehicle_value must be a positive number (ACV / FMV).",
        }

    fmv_f = float(fmv)
    base_loss = round(0.10 * fmv_f, 2)
    dmg, basis, ratio = _resolve_damage_multiplier(fmv_f, repair_cost, damage_severity_tier)
    mil = _mileage_multiplier(mileage)
    dv = round(base_loss * dmg * mil, 2)

    msg_parts = [
        f"Georgia 17c-style estimate: ${dv:,.2f}",
        f"(base 10% cap ${base_loss:,.2f} × damage × mileage).",
    ]
    if basis == "default_assumption":
        msg_parts.append("Damage tier/repair cost not provided; using moderate default multiplier.")

    out: dict[str, Any] = {
        "diminished_value": dv,
        "required": True,
        "state": "Georgia",
        "formula": "ga_17c",
        "base_value_loss_cap": base_loss,
        "damage_multiplier": dmg,
        "mileage_multiplier": mil,
        "damage_basis": basis,
        "message": " ".join(msg_parts),
    }
    if ratio is not None:
        out["repair_cost_ratio"] = round(ratio, 4)
    if mileage is not None:
        out["mileage_used"] = int(mileage)
    return out


def compute_diminished_value_payload(
    vehicle_value: float,
    loss_state: str | None,
    *,
    mileage: int | None = None,
    vehicle_year: int | None = None,
    repair_cost: float | None = None,
    damage_severity_tier: str | None = None,
) -> dict[str, Any]:
    """Build the JSON-serializable payload for ``calculate_diminished_value`` tools."""
    rules = get_state_rules(loss_state)
    st = loss_state or "unknown"

    if not rules or not rules.diminished_value_required:
        return {
            "diminished_value": 0.0,
            "required": False,
            "state": st if isinstance(st, str) else "unknown",
            "message": "Diminished value not required in this state.",
        }

    if rules.diminished_value_formula == "ga_17c":
        payload = calculate_ga_17c_diminished_value(
            vehicle_value,
            mileage=mileage,
            repair_cost=repair_cost,
            damage_severity_tier=damage_severity_tier,
        )
        if vehicle_year is not None:
            try:
                payload["vehicle_year"] = int(vehicle_year)
            except (TypeError, ValueError):
                payload["vehicle_year"] = vehicle_year
        return payload

    cap_pct = 0.10
    dv = round(float(vehicle_value) * cap_pct, 2) if vehicle_value > 0 else 0.0
    return {
        "diminished_value": dv,
        "required": True,
        "state": rules.state,
        "formula": "generic_cap_10pct",
        "cap_percent": cap_pct * 100,
        "message": (
            f"State requires diminished value consideration; no specific formula is configured. "
            f"Conservative cap estimate: ${dv:,.2f} ({cap_pct * 100:.0f}% of ACV)."
        ),
    }
