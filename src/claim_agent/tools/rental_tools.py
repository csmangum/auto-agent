"""Rental reimbursement workflow tools.

CrewAI tools call *_impl with ctx=None; get_policy_adapter() is used when
ClaimContext is not provided. See rental_logic module docstring.
"""

from __future__ import annotations

from crewai.tools import tool

from claim_agent.tools.rental_logic import (
    check_rental_coverage_impl,
    get_rental_limits_impl,
    process_rental_reimbursement_impl,
)


@tool("Check Rental Coverage")
def check_rental_coverage(policy_number: str) -> str:
    """Check if a policy has rental reimbursement (loss-of-use) coverage.

    Args:
        policy_number: The insurance policy number to check.

    Returns:
        JSON with eligible (bool), daily_limit, aggregate_limit, and message.
    """
    return check_rental_coverage_impl(policy_number=policy_number)


@tool("Get Rental Limits")
def get_rental_limits(policy_number: str) -> str:
    """Get rental reimbursement limits for a policy (daily, aggregate, max days).

    Args:
        policy_number: The insurance policy number.

    Returns:
        JSON with daily_limit, aggregate_limit, and max_days.
    """
    return get_rental_limits_impl(policy_number=policy_number)


@tool("Process Rental Reimbursement")
def process_rental_reimbursement(
    claim_id: str,
    amount: float,
    rental_days: int,
    policy_number: str,
) -> str:
    """Process rental reimbursement for an approved rental.

    Validates amount against policy limits before approving.

    Args:
        claim_id: The claim ID.
        amount: Reimbursement amount in USD.
        rental_days: Number of rental days.
        policy_number: Policy number for limit validation.

    Returns:
        JSON with reimbursement_id, amount, status, and message.
    """
    return process_rental_reimbursement_impl(
        claim_id=claim_id,
        amount=amount,
        rental_days=rental_days,
        policy_number=policy_number,
    )
