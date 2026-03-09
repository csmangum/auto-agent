"""Rental reimbursement logic: coverage check, limits, and reimbursement processing."""

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

# Coverage types that typically include rental reimbursement (Part D / physical damage)
RENTAL_ELIGIBLE_COVERAGES = frozenset({"comprehensive", "collision", "full_coverage"})


def check_rental_coverage_impl(
    policy_number: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Check if policy has rental reimbursement coverage and return limits.

    Uses policy rental_reimbursement or transportation_expenses when present;
    otherwise infers from coverage type (comprehensive/collision/full_coverage = eligible).
    """
    if not policy_number or not isinstance(policy_number, str):
        return json.dumps(
            {
                "eligible": False,
                "daily_limit": None,
                "aggregate_limit": None,
                "message": "Invalid policy number",
            }
        )
    policy_number = policy_number.strip()
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
    coverage = policy.get("coverage", "")
    if rental and isinstance(rental, dict):
        daily = rental.get("daily_limit")
        aggregate = rental.get("aggregate_limit")
        return json.dumps(
            {
                "eligible": True,
                "daily_limit": float(daily) if daily is not None else DEFAULT_DAILY_LIMIT,
                "aggregate_limit": float(aggregate)
                if aggregate is not None
                else DEFAULT_AGGREGATE_LIMIT,
                "message": "Rental reimbursement coverage found",
            }
        )
    if coverage and str(coverage).lower() in RENTAL_ELIGIBLE_COVERAGES:
        return json.dumps(
            {
                "eligible": True,
                "daily_limit": DEFAULT_DAILY_LIMIT,
                "aggregate_limit": DEFAULT_AGGREGATE_LIMIT,
                "message": f"Coverage type '{coverage}' typically includes rental; using default limits",
            }
        )
    return json.dumps(
        {
            "eligible": False,
            "daily_limit": None,
            "aggregate_limit": None,
            "message": f"Policy coverage '{coverage}' does not include rental reimbursement",
        }
    )


def get_rental_limits_impl(
    policy_number: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Get rental reimbursement limits for a policy.

    Returns daily_limit, aggregate_limit, and optional max_days.
    Falls back to compliance defaults when not specified.
    """
    if not policy_number or not isinstance(policy_number, str):
        return json.dumps(
            {
                "daily_limit": DEFAULT_DAILY_LIMIT,
                "aggregate_limit": DEFAULT_AGGREGATE_LIMIT,
                "max_days": DEFAULT_MAX_DAYS,
            }
        )
    policy_number = policy_number.strip()
    adapter = ctx.adapters.policy if ctx else get_policy_adapter()
    try:
        policy = adapter.get_policy(policy_number)
    except Exception as exc:
        logger.warning("Policy lookup failed for rental limits: %s", exc)
        return json.dumps(
            {
                "daily_limit": DEFAULT_DAILY_LIMIT,
                "aggregate_limit": DEFAULT_AGGREGATE_LIMIT,
                "max_days": DEFAULT_MAX_DAYS,
            }
        )
    if policy is None:
        return json.dumps(
            {
                "daily_limit": DEFAULT_DAILY_LIMIT,
                "aggregate_limit": DEFAULT_AGGREGATE_LIMIT,
                "max_days": DEFAULT_MAX_DAYS,
            }
        )
    rental = policy.get("rental_reimbursement") or policy.get("transportation_expenses")
    if rental and isinstance(rental, dict):
        daily = rental.get("daily_limit")
        aggregate = rental.get("aggregate_limit")
        max_days = rental.get("max_days")
        return json.dumps(
            {
                "daily_limit": float(daily) if daily is not None else DEFAULT_DAILY_LIMIT,
                "aggregate_limit": float(aggregate)
                if aggregate is not None
                else DEFAULT_AGGREGATE_LIMIT,
                "max_days": int(max_days) if max_days is not None else DEFAULT_MAX_DAYS,
            }
        )
    coverage = policy.get("coverage", "")
    if coverage and str(coverage).lower() in RENTAL_ELIGIBLE_COVERAGES:
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
    Mock implementation: generates reimbursement_id and returns confirmation.
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
    daily_limit = float(limits.get("daily_limit", DEFAULT_DAILY_LIMIT))
    aggregate_limit = float(limits.get("aggregate_limit", DEFAULT_AGGREGATE_LIMIT))
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
    return json.dumps(
        {
            "reimbursement_id": reimbursement_id,
            "amount": float(amount),
            "status": "approved",
            "message": f"Rental reimbursement {reimbursement_id} processed for claim {claim_id}",
        }
    )
