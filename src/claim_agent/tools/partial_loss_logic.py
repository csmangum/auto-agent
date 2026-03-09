"""Partial loss workflow logic: repair shops, parts, estimates, authorization."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Optional

from claim_agent.adapters.registry import get_parts_adapter, get_repair_shop_adapter
from claim_agent.config.settings import (
    DEFAULT_DEDUCTIBLE,
    LABOR_HOURS_MIN,
    LABOR_HOURS_PAINT_BODY,
    LABOR_HOURS_RNI_PER_PART,
    PARTIAL_LOSS_THRESHOLD,
)
from claim_agent.exceptions import AdapterError, DomainValidationError
from claim_agent.tools.policy_logic import query_policy_db_impl
from claim_agent.tools.valuation_logic import fetch_vehicle_value_impl

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)


def _get_shop_labor_rate(
    shop_id: Optional[str] = None,
    default: float = 75.0,
    shop: Optional[dict[str, Any]] = None,
    *,
    ctx: ClaimContext | None = None,
) -> float:
    """Return labor rate for shop_id, or default if not found."""
    if shop is not None:
        return shop.get("labor_rate_per_hour", default)
    if not shop_id:
        return default
    adapter = ctx.adapters.repair_shop if ctx else get_repair_shop_adapter()
    shop = adapter.get_shop(shop_id)
    if shop is None:
        return default
    return shop.get("labor_rate_per_hour", default)


def get_available_repair_shops_impl(
    location: Optional[str] = None,
    vehicle_make: Optional[str] = None,
    network_type: Optional[str] = None,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Get list of available repair shops, optionally filtered."""
    adapter = ctx.adapters.repair_shop if ctx else get_repair_shop_adapter()
    shops = adapter.get_shops()

    available_shops = []
    for shop_id, shop_data in shops.items():
        if not shop_data.get("capacity_available", False):
            continue

        if network_type and shop_data.get("network", "").lower() != network_type.lower():
            continue

        if location:
            shop_address = shop_data.get("address", "").lower()
            if location.lower() not in shop_address:
                continue

        if vehicle_make and vehicle_make.lower() == "tesla":
            certifications = shop_data.get("certifications", [])
            specialties = shop_data.get("specialties", [])
            has_ev_cert = (any("tesla" in c.lower() for c in certifications) or
                          any("electric" in s.lower() for s in specialties))
            shop_data = {**shop_data, "ev_certified": has_ev_cert}

        available_shops.append({
            "shop_id": shop_id,
            **shop_data,
        })

    available_shops.sort(key=lambda x: (-x.get("rating", 0), x.get("average_wait_days", 999)))

    return json.dumps({
        "shop_count": len(available_shops),
        "shops": available_shops,
    })


def assign_repair_shop_impl(
    claim_id: str,
    shop_id: str,
    estimated_repair_days: Optional[int] = None,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Assign a repair shop to a partial loss claim."""
    adapter = ctx.adapters.repair_shop if ctx else get_repair_shop_adapter()
    shop = adapter.get_shop(shop_id)

    if shop is None:
        return json.dumps({
            "success": False,
            "error": f"Repair shop {shop_id} not found",
        })

    if not shop.get("capacity_available", False):
        return json.dumps({
            "success": False,
            "error": f"Repair shop {shop['name']} does not have available capacity",
        })

    wait_days = shop.get("average_wait_days", 3)
    repair_days = estimated_repair_days or 5

    start_date = datetime.now() + timedelta(days=wait_days)
    completion_date = start_date + timedelta(days=repair_days)

    assignment = {
        "success": True,
        "claim_id": claim_id,
        "shop_id": shop_id,
        "shop_name": shop.get("name", ""),
        "address": shop.get("address", ""),
        "phone": shop.get("phone", ""),
        "labor_rate_per_hour": _get_shop_labor_rate(shop=shop, default=75.0),
        "network": shop.get("network", "standard"),
        "estimated_start_date": start_date.strftime("%Y-%m-%d"),
        "estimated_completion_date": completion_date.strftime("%Y-%m-%d"),
        "estimated_repair_days": repair_days,
        "confirmation_number": f"RSA-{uuid.uuid4().hex[:8].upper()}",
    }

    return json.dumps(assignment)


def get_parts_catalog_impl(
    damage_description: str,
    vehicle_make: str,
    part_type_preference: str = "aftermarket",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Get recommended parts from catalog based on damage description."""
    adapter = ctx.adapters.parts if ctx else get_parts_adapter()
    parts_catalog = adapter.get_catalog()

    damage_to_parts = {
        "front bumper": ["PART-BUMPER-FRONT"],
        "rear bumper": ["PART-BUMPER-REAR"],
        "front door": ["PART-DOOR-FRONT"],
        "rear door": ["PART-DOOR-REAR"],
        "side mirror": ["PART-MIRROR-SIDE"],
        "quarter panel": ["PART-QUARTER-PANEL"],
        "bumper": ["PART-BUMPER-FRONT", "PART-BUMPER-REAR"],
        "fender": ["PART-FENDER-FRONT"],
        "hood": ["PART-HOOD"],
        "door": ["PART-DOOR-FRONT", "PART-DOOR-REAR"],
        "headlight": ["PART-HEADLIGHT"],
        "taillight": ["PART-TAILLIGHT"],
        "mirror": ["PART-MIRROR-SIDE"],
        "windshield": ["PART-WINDSHIELD"],
        "radiator": ["PART-RADIATOR"],
        "airbag": ["PART-AIRBAG-DRIVER", "PART-AIRBAG-PASSENGER"],
        "grille": ["PART-GRILLE"],
        "trunk": ["PART-TRUNK-LID"],
    }

    damage_lower = damage_description.lower()
    recommended_parts = []
    seen_part_ids = set()
    for keyword, part_ids in sorted(damage_to_parts.items(), key=lambda kv: len(kv[0]), reverse=True):
        if keyword not in damage_lower:
            continue
        if keyword == "bumper" and ("front bumper" in damage_lower or "rear bumper" in damage_lower):
            continue
        if keyword == "door" and ("front door" in damage_lower or "rear door" in damage_lower):
            continue
        if keyword == "mirror" and "side mirror" in damage_lower:
            continue
        for part_id in part_ids:
            if part_id in seen_part_ids:
                continue
            seen_part_ids.add(part_id)

            if part_id in parts_catalog:
                part = parts_catalog[part_id]

                compatible_makes = part.get("compatible_makes", [])
                vehicle_make_norm = (
                    vehicle_make.strip().lower() if isinstance(vehicle_make, str) else ""
                )
                compatible_norm = [
                    m.strip().lower() for m in compatible_makes if isinstance(m, str)
                ]
                is_compatible = (
                    not compatible_makes or vehicle_make_norm in compatible_norm
                )

                selected_type = part_type_preference
                if part_type_preference == "oem":
                    price = part.get("oem_price")
                elif part_type_preference == "refurbished":
                    price = part.get("refurbished_price") or part.get("aftermarket_price")
                else:
                    price = part.get("aftermarket_price") or part.get("oem_price")

                if price is None:
                    price = part.get("oem_price", 0)
                    selected_type = "oem"

                recommended_parts.append({
                    "part_id": part_id,
                    "part_name": part.get("name", ""),
                    "category": part.get("category", ""),
                    "selected_type": selected_type,
                    "price": price,
                    "oem_price": part.get("oem_price"),
                    "aftermarket_price": part.get("aftermarket_price"),
                    "refurbished_price": part.get("refurbished_price"),
                    "availability": part.get("availability", "unknown"),
                    "lead_time_days": part.get("lead_time_days", 3),
                    "is_compatible": is_compatible,
                })

    total_cost = sum(p["price"] for p in recommended_parts if p["price"])

    return json.dumps({
        "damage_description": damage_description,
        "vehicle_make": vehicle_make,
        "part_type_preference": part_type_preference,
        "parts_count": len(recommended_parts),
        "parts": recommended_parts,
        "total_parts_cost": round(total_cost, 2),
    })


def create_parts_order_impl(
    claim_id: str,
    parts: list[dict],
    shop_id: str | None = None,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Create a parts order for a partial loss claim."""
    if not parts or not isinstance(parts, list):
        return json.dumps({
            "success": False,
            "error": "No parts specified for order",
        })

    adapter = ctx.adapters.parts if ctx else get_parts_adapter()
    parts_catalog = adapter.get_catalog()

    order_items = []
    total_cost = 0.0
    max_lead_time = 0

    for part_request in parts:
        part_id = part_request.get("part_id", "")
        quantity = part_request.get("quantity", 1)
        part_type = part_request.get("part_type", "aftermarket")

        if part_id not in parts_catalog:
            continue

        part = parts_catalog[part_id]

        if part_type == "oem":
            unit_price = part.get("oem_price")
        elif part_type == "refurbished":
            unit_price = part.get("refurbished_price") or part.get("aftermarket_price")
        else:
            unit_price = part.get("aftermarket_price") or part.get("oem_price")

        if unit_price is None:
            unit_price = part.get("oem_price", 0)

        item_total = unit_price * quantity
        lead_time = part.get("lead_time_days", 3)
        max_lead_time = max(max_lead_time, lead_time)

        order_items.append({
            "part_id": part_id,
            "part_name": part.get("name", ""),
            "quantity": quantity,
            "part_type": part_type,
            "unit_price": unit_price,
            "total_price": round(item_total, 2),
            "availability": part.get("availability", "unknown"),
            "lead_time_days": lead_time,
        })

        total_cost += item_total

    if not order_items:
        return json.dumps({
            "success": False,
            "error": "No valid parts found in catalog",
        })

    delivery_date = datetime.now() + timedelta(days=max_lead_time + 1)

    order = {
        "success": True,
        "order_id": f"PO-{uuid.uuid4().hex[:8].upper()}",
        "claim_id": claim_id,
        "shop_id": shop_id,
        "items": order_items,
        "items_count": len(order_items),
        "total_parts_cost": round(total_cost, 2),
        "order_status": "ordered",
        "estimated_delivery_date": delivery_date.strftime("%Y-%m-%d"),
        "order_placed_at": datetime.now().isoformat(),
    }

    return json.dumps(order)


def calculate_repair_estimate_impl(
    damage_description: str,
    vehicle_make: str,
    vehicle_year: int,
    policy_number: str,
    shop_id: Optional[str] = None,
    part_type_preference: str = "aftermarket",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Calculate a complete repair estimate for a partial loss claim."""
    shop_adapter = ctx.adapters.repair_shop if ctx else get_repair_shop_adapter()

    parts_result = get_parts_catalog_impl(damage_description, vehicle_make, part_type_preference, ctx=ctx)
    parts_data = json.loads(parts_result)
    parts_cost = parts_data.get("total_parts_cost", 0.0)
    parts_list = parts_data.get("parts", [])

    labor_rate = _get_shop_labor_rate(shop_id, 75.0, ctx=ctx)

    labor_operations = shop_adapter.get_labor_operations()
    base_labor_hours = 0.0
    damage_lower = damage_description.lower()

    has_body_part = False
    for part in parts_list:
        base_labor_hours += LABOR_HOURS_RNI_PER_PART
        if part.get("category") == "body":
            base_labor_hours += LABOR_HOURS_PAINT_BODY
            has_body_part = True

    if ("paint" in damage_lower or "scratch" in damage_lower) and not has_body_part:
        base_labor_hours += labor_operations.get("LABOR-BLEND-PAINT", {}).get("base_hours", LABOR_HOURS_PAINT_BODY)
    if "dent" in damage_lower and "minor" in damage_lower:
        base_labor_hours += labor_operations.get("LABOR-PDR", {}).get("base_hours", 1.0)
    if "frame" in damage_lower:
        base_labor_hours += labor_operations.get("LABOR-FRAME-PULL", {}).get("base_hours", 3.0)
    if "alignment" in damage_lower or "wheel" in damage_lower:
        base_labor_hours += labor_operations.get("LABOR-ALIGNMENT", {}).get("base_hours", 1.0)
    if "sensor" in damage_lower or "camera" in damage_lower or "adas" in damage_lower:
        base_labor_hours += labor_operations.get("LABOR-CALIBRATION", {}).get("base_hours", LABOR_HOURS_PAINT_BODY)

    if base_labor_hours < LABOR_HOURS_MIN:
        base_labor_hours = LABOR_HOURS_MIN

    labor_cost = round(base_labor_hours * labor_rate, 2)
    total_estimate = round(parts_cost + labor_cost, 2)

    try:
        policy_result = query_policy_db_impl(policy_number, ctx=ctx)
    except (DomainValidationError, AdapterError):
        deductible = DEFAULT_DEDUCTIBLE
    else:
        policy_data = json.loads(policy_result)
        deductible = policy_data.get("deductible", DEFAULT_DEDUCTIBLE) if policy_data.get("valid") else DEFAULT_DEDUCTIBLE

    customer_pays = min(deductible, total_estimate)
    insurance_pays = max(0, total_estimate - deductible)

    vin = ""
    vehicle_value_result = fetch_vehicle_value_impl(vin, vehicle_year, vehicle_make, "", ctx=ctx)
    vehicle_value_data = json.loads(vehicle_value_result)
    vehicle_value = vehicle_value_data.get("value", 15000)

    is_total_loss = total_estimate >= (PARTIAL_LOSS_THRESHOLD * vehicle_value)

    estimate = {
        "damage_description": damage_description,
        "vehicle_make": vehicle_make,
        "vehicle_year": vehicle_year,
        "parts": parts_list,
        "parts_cost": parts_cost,
        "labor_hours": round(base_labor_hours, 1),
        "labor_rate": labor_rate,
        "labor_cost": labor_cost,
        "total_estimate": total_estimate,
        "deductible": deductible,
        "customer_pays": customer_pays,
        "insurance_pays": insurance_pays,
        "vehicle_value": vehicle_value,
        "repair_to_value_ratio": round(total_estimate / vehicle_value, 2) if vehicle_value > 0 else 0,
        "is_total_loss": is_total_loss,
        "total_loss_threshold": PARTIAL_LOSS_THRESHOLD,
        "part_type_preference": part_type_preference,
        "shop_id": shop_id,
    }

    return json.dumps(estimate)


def generate_repair_authorization_impl(
    claim_id: str,
    shop_id: str,
    repair_estimate: dict[str, Any],
    customer_approved: bool = True,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Generate a repair authorization document for a partial loss claim.

    Returns JSON with authorization details. Does NOT dispatch webhooks;
    the caller (tool wrapper) is responsible for notification side-effects.
    """
    adapter = ctx.adapters.repair_shop if ctx else get_repair_shop_adapter()
    shop = adapter.get_shop(shop_id) or {}

    authorization = {
        "authorization_id": f"RA-{uuid.uuid4().hex[:8].upper()}",
        "claim_id": claim_id,
        "shop_id": shop_id,
        "shop_name": shop.get("name", "Unknown Shop"),
        "shop_address": shop.get("address", ""),
        "shop_phone": shop.get("phone", ""),
        "authorized_amount": repair_estimate.get("total_estimate", 0),
        "parts_authorized": repair_estimate.get("parts_cost", 0),
        "labor_authorized": repair_estimate.get("labor_cost", 0),
        "deductible": repair_estimate.get("deductible", 0),
        "customer_responsibility": repair_estimate.get("customer_pays", 0),
        "insurance_responsibility": repair_estimate.get("insurance_pays", 0),
        "customer_approved": customer_approved,
        "authorization_status": "approved" if customer_approved else "pending_approval",
        "authorization_date": datetime.now().strftime("%Y-%m-%d"),
        "valid_until": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "terms": [
            "Repair must be completed within 30 days of authorization",
            "Any additional damage found must be reported before repair",
            "Supplemental authorization required for additional costs over 10%",
            "Original damaged parts must be retained for inspection if requested",
        ],
        "shop_webhook_url": shop.get("webhook_url"),
    }

    return json.dumps(authorization)


def get_original_repair_estimate_impl(
    claim_id: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Retrieve the original repair estimate from the claim's partial loss workflow.

    Parses the most recent partial_loss workflow run to extract estimate fields.
    Returns JSON with total_estimate, parts_cost, labor_cost, authorization_id,
    shop_id, and related fields. Returns error JSON if claim not found or no
    partial loss workflow exists.
    """
    from claim_agent.db.repository import ClaimRepository

    repo = ctx.repo if ctx else ClaimRepository()
    claim = repo.get_claim(claim_id)
    if claim is None:
        return json.dumps({"error": f"Claim not found: {claim_id}"})

    runs = repo.get_workflow_runs(claim_id, limit=10)
    for run in runs:
        if run.get("claim_type") != "partial_loss":
            continue
        wf_output = run.get("workflow_output") or ""
        parsed = _parse_partial_loss_workflow_output(wf_output)
        if parsed:
            parsed["claim_id"] = claim_id
            parsed["original_damage_description"] = claim.get("damage_description")
            return json.dumps(parsed)

    return json.dumps({
        "error": f"No partial loss workflow found for claim {claim_id}",
        "claim_id": claim_id,
    })


def _parse_partial_loss_workflow_output(wf_output: str) -> dict[str, Any] | None:
    """Extract estimate and authorization fields from partial loss workflow output."""
    import re

    result: dict[str, Any] = {}
    # Try parsing entire output as JSON first (e.g. from workflow_runs storage)
    wf_stripped = wf_output.strip()
    if wf_stripped.startswith("{") and wf_stripped.endswith("}"):
        try:
            data = json.loads(wf_output)
            if isinstance(data, dict):
                for key in (
                    "total_estimate", "authorized_amount", "parts_cost", "labor_cost",
                    "deductible", "customer_pays", "insurance_pays", "payout_amount",
                    "authorization_id", "shop_id", "shop_name", "shop_phone",
                    "estimated_repair_days",
                ):
                    if key in data and data[key] is not None:
                        result[key] = data[key]
                if result:
                    return result
        except json.JSONDecodeError:
            pass

    # Try JSON block in markdown
    code_block = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.DOTALL)
    for match in code_block.finditer(wf_output):
        try:
            data = json.loads(match.group(1).strip())
            if isinstance(data, dict):
                for key in (
                    "total_estimate", "authorized_amount", "parts_cost", "labor_cost",
                    "deductible", "customer_pays", "insurance_pays", "payout_amount",
                    "authorization_id", "shop_id", "shop_name", "shop_phone",
                    "estimated_repair_days",
                ):
                    if key in data and data[key] is not None:
                        result[key] = data[key]
                if result:
                    return result
        except json.JSONDecodeError:
            continue

    # Fallback: regex for common patterns
    patterns = [
        (r"total_estimate[:\s]*(\d+\.?\d*)", "total_estimate"),
        (r"authorized_amount[:\s]*(\d+\.?\d*)", "authorized_amount"),
        (r"parts_cost[:\s]*(\d+\.?\d*)", "parts_cost"),
        (r"labor_cost[:\s]*(\d+\.?\d*)", "labor_cost"),
        (r"insurance_pays[:\s]*(\d+\.?\d*)", "insurance_pays"),
        (r"payout_amount[:\s]*(\d+\.?\d*)", "payout_amount"),
        (r"authorization_id[:\s]*['\"]?([A-Za-z0-9\-]+)['\"]?", "authorization_id"),
        (r"shop_id[:\s]*['\"]?([A-Za-z0-9\-]+)['\"]?", "shop_id"),
        (r"estimated_repair_days[:\s]*(\d+)", "estimated_repair_days"),
    ]
    numeric_keys = {"total_estimate", "authorized_amount", "parts_cost", "labor_cost", "insurance_pays", "payout_amount", "deductible", "customer_pays", "estimated_repair_days"}
    for pattern, key in patterns:
        m = re.search(pattern, wf_output, re.IGNORECASE)
        if m:
            val = m.group(1)
            if key in numeric_keys:
                try:
                    result[key] = float(val.replace(",", ""))
                except (ValueError, AttributeError):
                    result[key] = val
            else:
                result[key] = val

    return result if result else None


def calculate_supplemental_estimate_impl(
    supplemental_damage_description: str,
    vehicle_make: str,
    vehicle_year: int,
    policy_number: str,
    shop_id: Optional[str] = None,
    part_type_preference: str = "aftermarket",
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Calculate repair estimate for supplemental (additional) damage only.

    Reuses calculate_repair_estimate_impl with the supplemental damage description.
    Deductible is typically already applied to the original estimate; supplemental
    insurance_pays is usually the full supplemental amount (no additional deductible).
    """
    estimate_json = calculate_repair_estimate_impl(
        damage_description=supplemental_damage_description,
        vehicle_make=vehicle_make,
        vehicle_year=vehicle_year,
        policy_number=policy_number,
        shop_id=shop_id,
        part_type_preference=part_type_preference,
        ctx=ctx,
    )
    estimate = json.loads(estimate_json)
    if "error" in estimate:
        return estimate_json
    estimate["supplemental_damage_description"] = supplemental_damage_description
    estimate["is_supplemental"] = True
    total_estimate = estimate.get("total_estimate", 0)
    # For supplemental estimates, no additional deductible should be applied.
    # Override any deductible/customer_pays set by calculate_repair_estimate_impl.
    estimate["deductible"] = 0
    estimate["customer_pays"] = 0
    estimate["insurance_pays"] = total_estimate
    return json.dumps(estimate)


def update_repair_authorization_impl(
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
    authorization_id: Optional[str] = None,
    customer_approved: bool = True,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Update repair authorization with supplemental amounts.

    Creates a supplemental authorization record and returns combined totals.
    Original deductible is not re-applied to supplemental; insurance pays
    the supplemental amount.

    Note: The supplemental authorization (RA-SUP-xxx) is computed and returned
    in workflow output but not persisted to a dedicated table. Same as
    generate_repair_authorization. The orchestrator updates claim payout_amount
    from extracted values. For auditability, consider extending workflow_runs
    or adding an authorizations table in future.
    """
    adapter = ctx.adapters.repair_shop if ctx else get_repair_shop_adapter()
    shop = adapter.get_shop(shop_id) or {}

    combined_total = original_total + supplemental_total
    combined_parts = original_parts + supplemental_parts
    combined_labor = original_labor + supplemental_labor
    combined_insurance_pays = original_insurance_pays + supplemental_insurance_pays

    supplemental_auth_id = f"RA-SUP-{uuid.uuid4().hex[:8].upper()}"

    result = {
        "success": True,
        "claim_id": claim_id,
        "shop_id": shop_id,
        "original_authorization_id": authorization_id,
        "supplemental_authorization_id": supplemental_auth_id,
        "original_total": original_total,
        "supplemental_total": supplemental_total,
        "combined_total": round(combined_total, 2),
        "combined_parts": round(combined_parts, 2),
        "combined_labor": round(combined_labor, 2),
        "supplemental_insurance_pays": supplemental_insurance_pays,
        "combined_insurance_pays": round(combined_insurance_pays, 2),
        "shop_name": shop.get("name", "Unknown Shop"),
        "shop_phone": shop.get("phone", ""),
        "authorization_status": "approved" if customer_approved else "pending_approval",
        "authorization_date": datetime.now().strftime("%Y-%m-%d"),
        "valid_until": (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d"),
        "shop_webhook_url": shop.get("webhook_url"),
    }
    return json.dumps(result)
