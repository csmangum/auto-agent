"""Mock document generator for claim-related documents.

Generates plausible repair estimates and damage photo URLs without real APIs.
Deterministic when MOCK_CREW_SEED is set.
"""

import hashlib
import json
import logging
import random
from typing import Any

from claim_agent.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Repair estimate helpers
# ---------------------------------------------------------------------------

_LABOR_RATE_PER_HOUR = 125.0  # USD per hour, typical body-shop rate

_DAMAGE_PART_CATALOG: list[dict[str, Any]] = [
    {"part": "Front Bumper Cover", "part_cost": 450.0, "labor_hours": 3.0},
    {"part": "Rear Bumper Cover", "part_cost": 420.0, "labor_hours": 2.5},
    {"part": "Hood", "part_cost": 800.0, "labor_hours": 4.0},
    {"part": "Front Fender (Left)", "part_cost": 380.0, "labor_hours": 3.5},
    {"part": "Front Fender (Right)", "part_cost": 380.0, "labor_hours": 3.5},
    {"part": "Rear Quarter Panel (Left)", "part_cost": 950.0, "labor_hours": 6.0},
    {"part": "Rear Quarter Panel (Right)", "part_cost": 950.0, "labor_hours": 6.0},
    {"part": "Driver Door", "part_cost": 700.0, "labor_hours": 4.0},
    {"part": "Passenger Door", "part_cost": 700.0, "labor_hours": 4.0},
    {"part": "Windshield", "part_cost": 600.0, "labor_hours": 2.0},
    {"part": "Rear Window", "part_cost": 500.0, "labor_hours": 2.0},
    {"part": "Headlight Assembly (Left)", "part_cost": 350.0, "labor_hours": 1.5},
    {"part": "Headlight Assembly (Right)", "part_cost": 350.0, "labor_hours": 1.5},
    {"part": "Taillight Assembly (Left)", "part_cost": 280.0, "labor_hours": 1.5},
    {"part": "Taillight Assembly (Right)", "part_cost": 280.0, "labor_hours": 1.5},
    {"part": "Radiator", "part_cost": 550.0, "labor_hours": 3.0},
    {"part": "Airbag Module", "part_cost": 1200.0, "labor_hours": 2.0},
    {"part": "Paint and Refinish", "part_cost": 0.0, "labor_hours": 8.0},
]

_KEYWORDS_TO_PARTS: dict[str, list[str]] = {
    "front": ["Front Bumper Cover", "Hood", "Headlight Assembly (Left)", "Headlight Assembly (Right)"],
    "rear": ["Rear Bumper Cover", "Taillight Assembly (Left)", "Rear Window"],
    "side": ["Front Fender (Left)", "Driver Door", "Rear Quarter Panel (Left)"],
    "fender": ["Front Fender (Left)", "Front Fender (Right)"],
    "bumper": ["Front Bumper Cover"],
    "hood": ["Hood"],
    "door": ["Driver Door", "Passenger Door"],
    "windshield": ["Windshield"],
    "window": ["Windshield", "Rear Window"],
    "headlight": ["Headlight Assembly (Left)", "Headlight Assembly (Right)"],
    "taillight": ["Taillight Assembly (Left)", "Taillight Assembly (Right)"],
    "total loss": [
        "Hood",
        "Front Bumper Cover",
        "Radiator",
        "Headlight Assembly (Left)",
        "Headlight Assembly (Right)",
        "Airbag Module",
        "Windshield",
        "Paint and Refinish",
    ],
    "airbag": ["Airbag Module"],
    "radiator": ["Radiator"],
}

_SHOP_NAMES = [
    "AutoFix Body Shop",
    "Premier Collision Center",
    "Precision Auto Repair",
    "City Collision Works",
    "Star Automotive",
]


def _select_parts(claim_context: dict[str, Any], rng: random.Random) -> list[str]:
    """Select relevant parts based on damage description keywords."""
    damage = (claim_context.get("damage_description") or "").lower()
    incident = (claim_context.get("incident_description") or "").lower()
    combined = f"{damage} {incident}"

    selected: set[str] = set()
    for keyword, parts in _KEYWORDS_TO_PARTS.items():
        if keyword in combined:
            selected.update(parts)

    # Always add paint/refinish when any body work is needed
    if selected:
        selected.add("Paint and Refinish")

    # Fall back to a small default set when no keywords match
    if not selected:
        default_parts = ["Front Bumper Cover", "Paint and Refinish"]
        selected.update(default_parts)

    return sorted(selected)


def _build_line_items(
    part_names: list[str], rng: random.Random
) -> list[dict[str, Any]]:
    """Build line-item dicts for selected parts with slight cost jitter."""
    catalog = {entry["part"]: entry for entry in _DAMAGE_PART_CATALOG}
    items: list[dict[str, Any]] = []
    for name in part_names:
        entry = catalog.get(name)
        if entry is None:
            continue
        # Add ±10% jitter to make estimates feel realistic
        jitter = rng.uniform(0.90, 1.10)
        part_cost = round(entry["part_cost"] * jitter, 2)
        labor_hours = round(entry["labor_hours"] * jitter, 2)
        labor_cost = round(labor_hours * _LABOR_RATE_PER_HOUR, 2)
        items.append(
            {
                "description": name,
                "part_cost": part_cost,
                "labor_hours": labor_hours,
                "labor_cost": labor_cost,
                "line_total": round(part_cost + labor_cost, 2),
            }
        )
    return items


def generate_repair_estimate(claim_context: dict[str, Any]) -> dict[str, Any]:
    """Generate a plausible mock repair estimate for a claim.

    The estimate contains line items (parts + labor), a shop name, and totals.
    Numbers are derived from ``damage_description`` / ``estimated_damage`` in the
    claim context so that related claims produce similar figures.

    When ``MOCK_CREW_SEED`` is set the output is deterministic for the same
    *claim_context*.

    Args:
        claim_context: Claim data dict.  Recognised keys:
            ``damage_description``, ``incident_description``,
            ``estimated_damage`` (numeric override for the total),
            ``vehicle_year``, ``vehicle_make``, ``vehicle_model``,
            ``claim_id``.

    Returns:
        Dict with keys ``line_items``, ``subtotal_parts``, ``subtotal_labor``,
        ``subtotal``, ``tax``, ``total``, ``shop_name``, ``currency``.
    """
    seed = get_settings().mock_crew.seed
    if seed is not None:
        ctx_str = json.dumps(claim_context, sort_keys=True)
        derived_seed = int(hashlib.sha256(f"{ctx_str}:{seed}".encode()).hexdigest(), 16) % (2**32)
    else:
        derived_seed = None

    rng = random.Random(derived_seed)

    part_names = _select_parts(claim_context, rng)
    line_items = _build_line_items(part_names, rng)

    subtotal_parts = round(sum(item["part_cost"] for item in line_items), 2)
    subtotal_labor = round(sum(item["labor_cost"] for item in line_items), 2)
    subtotal = round(subtotal_parts + subtotal_labor, 2)
    tax_rate = 0.08
    tax = round(subtotal * tax_rate, 2)
    total = round(subtotal + tax, 2)

    # Honour an explicit estimated_damage override if provided
    estimated_override = claim_context.get("estimated_damage")
    if estimated_override is not None:
        try:
            override_val = float(estimated_override)
            if override_val > 0:
                # Scale all monetary values proportionally
                scale = override_val / total if total else 1.0
                subtotal_parts = round(subtotal_parts * scale, 2)
                subtotal_labor = round(subtotal_labor * scale, 2)
                subtotal = round(subtotal_parts + subtotal_labor, 2)
                tax = round(subtotal * tax_rate, 2)
                total = round(subtotal + tax, 2)
                for item in line_items:
                    item["part_cost"] = round(item["part_cost"] * scale, 2)
                    item["labor_cost"] = round(item["labor_cost"] * scale, 2)
                    item["line_total"] = round(item["part_cost"] + item["labor_cost"], 2)
        except (TypeError, ValueError):
            pass

    shop_name = rng.choice(_SHOP_NAMES)

    vehicle_parts = " ".join(
        filter(
            None,
            [
                str(claim_context.get("vehicle_year", "")),
                str(claim_context.get("vehicle_make", "")),
                str(claim_context.get("vehicle_model", "")),
            ],
        )
    ).strip()

    return {
        "claim_id": claim_context.get("claim_id"),
        "vehicle": vehicle_parts or None,
        "shop_name": shop_name,
        "line_items": line_items,
        "subtotal_parts": subtotal_parts,
        "subtotal_labor": subtotal_labor,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "currency": "USD",
    }


# ---------------------------------------------------------------------------
# Damage photo URL
# ---------------------------------------------------------------------------


def generate_damage_photo_url(claim_context: dict[str, Any]) -> str:
    """Return a URL/path for a mock damage photo for the claim.

    Delegates to the image generator when ``MOCK_IMAGE_GENERATOR_ENABLED`` is
    set; otherwise returns a placeholder path consistent with attachment storage.

    Args:
        claim_context: Claim data dict passed through to the image generator.

    Returns:
        ``file://`` URL (from image generator) or a placeholder path string.
    """
    cfg = get_settings().mock_image
    if cfg.generator_enabled:
        from claim_agent.mock_crew.image_generator import generate_damage_image

        return generate_damage_image(claim_context, fallback_on_error=True)

    # Return a deterministic placeholder path so callers always get a string
    seed = get_settings().mock_crew.seed
    if seed is not None:
        ctx_str = json.dumps(claim_context, sort_keys=True)
        h = hashlib.sha256(f"{ctx_str}:{seed}".encode()).hexdigest()[:12]
        filename = f"mock_damage_{h}.png"
    else:
        claim_id = claim_context.get("claim_id", "unknown")
        filename = f"mock_damage_{claim_id}.png"

    base = get_settings().get_attachment_storage_base_path()
    out_path = base / "mock_generated" / filename
    return f"file://{out_path.resolve()}"
