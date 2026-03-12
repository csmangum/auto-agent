"""Rental reimbursement logic: coverage check, limits, and reimbursement processing.

Tools use get_policy_adapter() when ClaimContext is not provided (CrewAI tools
are not request-scoped). When ctx is passed, ctx.adapters.policy is used.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import TYPE_CHECKING

from claim_agent.adapters.registry import get_policy_adapter

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)

# Compliance defaults per CCR 2695.7(l) - daily and aggregate limits when not specified
DEFAULT_DAILY_LIMIT = 35.0
DEFAULT_AGGREGATE_LIMIT = 1050.0
DEFAULT_MAX_DAYS = 30

# Coverage types that typically include rental reimbursement (Part D / physical damage).
# "full_coverage" is a legacy misnomer; real policies use coverages array with collision/comprehensive.
RENTAL_ELIGIBLE_COVERAGES = frozenset({"comprehensive", "collision", "full_coverage"})

# In-memory idempotency cache for mock: (claim_id, amount, rental_days) -> reimbursement_id.
# TODO: Real implementation must persist to repository and enforce idempotency in DB.
_IDEMPOTENCY_CACHE: dict[tuple[str, float, int], str] = {}


def _parse_rental_limits(rental: dict | None) -> tuple[float, float, int]:
    """Extract daily_limit, aggregate_limit, max_days from policy rental block."""
    if not rental or not isinstance(rental, dict):
        return DEFAULT_DAILY_LIMIT, DEFAULT_AGGREGATE_LIMIT, DEFAULT_MAX_DAYS
    try:
        daily = float(rental["daily_limit"]) if rental.get("daily_limit") is not None else DEFAULT_DAILY_LIMIT
    except (TypeError, ValueError):
        daily = DEFAULT_DAILY_LIMIT
    try:
        agg = float(rental["aggregate_limit"]) if rental.get("aggregate_limit") is not None else DEFAULT_AGGREGATE_LIMIT
    except (TypeError, ValueError):
        agg = DEFAULT_AGGREGATE_LIMIT
    try:
        days = int(rental["max_days"]) if rental.get("max_days") is not None else DEFAULT_MAX_DAYS
    except (TypeError, ValueError):
        days = DEFAULT_MAX_DAYS
    return daily, agg, days


def check_rental_coverage_impl(
    policy_number: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Check if policy has rental reimbursement coverage and return limits.

    Uses policy rental_reimbursement or transportation_expenses when present;
    otherwise infers from coverage type (comprehensive/collision/full_coverage = eligible).
    """
    policy_number = policy_number.strip() if isinstance(policy_number, str) else ""
    if not policy_number:
        return json.dumps(
            {
                "eligible": False,
                "daily_limit": None,
                "aggregate_limit": None,
                "message": "Invalid policy number",
            }
        )
    adapter = ctx.adapters.policy if ctx else get_policy_adapter()
    try:
        policy = adapter.get_policy(policy_number)
    except Exception as exc:
        logger.warning("Policy lookup failed for rental coverage: %s", exc)
        return json.dumps(
            {
                "eligible": False,
                "daily_limit": None,
                "aggregate_limit": None,
                "message": "Policy lookup failed",
            }
        )
    if policy is None:
        return json.dumps(
            {
                "eligible": False,
                "daily_limit": None,
                "aggregate_limit": None,
                "message": "Policy not found",
            }
        )
    status = policy.get("status", "active")
    if isinstance(status, str) and status.lower() != "active":
        return json.dumps(
            {
                "eligible": False,
                "daily_limit": None,
                "aggregate_limit": None,
                "message": f"Policy is not active (status: {status})",
            }
        )
    rental = policy.get("rental_reimbursement") or policy.get("transportation_expenses")
    coverages = policy.get("coverages") or []
    coverage = policy.get("coverage", "")
    has_physical_damage = (
        "collision" in coverages
        or "comprehensive" in coverages
        or (coverage and str(coverage).lower() in RENTAL_ELIGIBLE_COVERAGES)
    )
    if rental and isinstance(rental, dict):
        daily_val, agg_val, max_days_val = _parse_rental_limits(rental)
        return json.dumps(
            {
                "eligible": True,
                "daily_limit": daily_val,
                "aggregate_limit": agg_val,
                "max_days": max_days_val,
                "message": "Rental reimbursement coverage found",
            }
        )
    if has_physical_damage:
        return json.dumps(
            {
                "eligible": True,
                "daily_limit": DEFAULT_DAILY_LIMIT,
                "aggregate_limit": DEFAULT_AGGREGATE_LIMIT,
                "max_days": DEFAULT_MAX_DAYS,
                "message": "Policy includes collision or comprehensive; using default rental limits",
            }
        )
    return json.dumps(
        {
            "eligible": False,
            "daily_limit": None,
            "aggregate_limit": None,
            "message": "Policy does not include collision or comprehensive coverage (rental requires physical damage coverage)",
        }
    )


def _error_limits(error: str) -> str:
    """Return error structure for get_rental_limits (invalid/missing policy)."""
    return json.dumps(
        {
            "error": error,
            "daily_limit": None,
            "aggregate_limit": None,
            "max_days": None,
        }
    )


def get_rental_limits_impl(
    policy_number: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Get rental reimbursement limits for a policy.

    Returns daily_limit, aggregate_limit, and max_days when policy is valid.
    Returns error structure (daily_limit/aggregate_limit/max_days = None) for
    invalid policy number, policy not found, or lookup failure.
    """
    policy_number = policy_number.strip() if isinstance(policy_number, str) else ""
    if not policy_number:
        return _error_limits("Invalid policy number")
    adapter = ctx.adapters.policy if ctx else get_policy_adapter()
    try:
        policy = adapter.get_policy(policy_number)
    except Exception as exc:
        logger.warning("Policy lookup failed for rental limits: %s", exc)
        return _error_limits("Policy lookup failed")
    if policy is None:
        return _error_limits("Policy not found")
    rental = policy.get("rental_reimbursement") or policy.get("transportation_expenses")
    coverages = policy.get("coverages") or []
    coverage = policy.get("coverage", "")
    has_physical_damage = (
        "collision" in coverages
        or "comprehensive" in coverages
        or (coverage and str(coverage).lower() in RENTAL_ELIGIBLE_COVERAGES)
    )
    if rental and isinstance(rental, dict):
        daily_val, agg_val, max_days_val = _parse_rental_limits(rental)
        return json.dumps(
            {
                "daily_limit": daily_val,
                "aggregate_limit": agg_val,
                "max_days": max_days_val,
            }
        )
    if has_physical_damage:
        return json.dumps(
            {
                "daily_limit": DEFAULT_DAILY_LIMIT,
                "aggregate_limit": DEFAULT_AGGREGATE_LIMIT,
                "max_days": DEFAULT_MAX_DAYS,
            }
        )
    return json.dumps(
        {
            "daily_limit": DEFAULT_DAILY_LIMIT,
            "aggregate_limit": DEFAULT_AGGREGATE_LIMIT,
            "max_days": DEFAULT_MAX_DAYS,
        }
    )


def process_rental_reimbursement_impl(
    claim_id: str,
    amount: float,
    rental_days: int,
    policy_number: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Process rental reimbursement for an approved rental.

    Validates amount against limits from get_rental_limits_impl.
    Idempotent: repeated calls with same (claim_id, amount, rental_days) return
    the same reimbursement_id (in-memory cache for mock).
    TODO: Real implementation must persist to repository and enforce
    idempotency in DB.
    """
    if not claim_id or not isinstance(claim_id, str):
        return json.dumps(
            {
                "reimbursement_id": "",
                "amount": 0.0,
                "status": "failed",
                "message": "Invalid claim_id",
            }
        )
    if not isinstance(amount, (int, float)) or amount < 0:
        return json.dumps(
            {
                "reimbursement_id": "",
                "amount": 0.0,
                "status": "failed",
                "message": "Invalid amount",
            }
        )
    if not isinstance(rental_days, int) or rental_days < 1:
        return json.dumps(
            {
                "reimbursement_id": "",
                "amount": 0.0,
                "status": "failed",
                "message": "Invalid rental_days",
            }
        )
    coverage_json = check_rental_coverage_impl(policy_number, ctx=ctx)
    try:
        coverage = json.loads(coverage_json)
    except json.JSONDecodeError:
        coverage = {}
    if not coverage.get("eligible", False):
        return json.dumps(
            {
                "reimbursement_id": "",
                "amount": 0.0,
                "status": "failed",
                "message": f"Policy {policy_number} does not have rental coverage",
            }
        )
    limits_json = get_rental_limits_impl(policy_number, ctx=ctx)
    try:
        limits = json.loads(limits_json)
    except json.JSONDecodeError:
        limits = {}
    if limits.get("error") or limits.get("daily_limit") is None:
        return json.dumps(
            {
                "reimbursement_id": "",
                "amount": 0.0,
                "status": "failed",
                "message": limits.get("error", "Could not retrieve policy limits"),
            }
        )
    idempotency_key = (claim_id, float(amount), rental_days)
    if idempotency_key in _IDEMPOTENCY_CACHE:
        rid = _IDEMPOTENCY_CACHE[idempotency_key]
        return json.dumps(
            {
                "reimbursement_id": rid,
                "amount": float(amount),
                "status": "approved",
                "message": f"Rental reimbursement {rid} already processed for claim {claim_id} (idempotent)",
            }
        )
    daily_limit = float(limits["daily_limit"])
    aggregate_limit = float(limits["aggregate_limit"])
    max_days = limits.get("max_days")
    if max_days is not None and rental_days > int(max_days):
        return json.dumps(
            {
                "reimbursement_id": "",
                "amount": 0.0,
                "status": "failed",
                "message": f"Rental days {rental_days} exceeds policy max_days {max_days}",
            }
        )
    max_amount = min(rental_days * daily_limit, aggregate_limit)
    if amount > max_amount:
        return json.dumps(
            {
                "reimbursement_id": "",
                "amount": 0.0,
                "status": "failed",
                "message": f"Amount {amount} exceeds limit {max_amount} (daily {daily_limit}, aggregate {aggregate_limit})",
            }
        )
    reimbursement_id = f"RENT-{uuid.uuid4().hex[:8].upper()}"
    _IDEMPOTENCY_CACHE[idempotency_key] = reimbursement_id
    return json.dumps(
        {
            "reimbursement_id": reimbursement_id,
            "amount": float(amount),
            "status": "approved",
            "message": f"Rental reimbursement {reimbursement_id} processed for claim {claim_id}",
        }
    )
