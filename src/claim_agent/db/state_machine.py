"""Claim state machine: valid transitions and guards.

Enforces compliance with claim lifecycle rules. Invalid transitions raise
InvalidClaimTransitionError and are logged for compliance alerting.
"""

from __future__ import annotations

import logging
from typing import Any

from claim_agent.db.constants import (
    CLAIM_STATUSES,
    STATUS_ARCHIVED,
    STATUS_CLOSED,
    STATUS_DENIED,
    STATUS_DISPUTE_RESOLVED,
    STATUS_DISPUTED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_FRAUD_CONFIRMED,
    STATUS_FRAUD_SUSPECTED,
    STATUS_NEEDS_REVIEW,
    STATUS_OPEN,
    STATUS_PARTIAL_LOSS,
    STATUS_PENDING,
    STATUS_PENDING_INFO,
    STATUS_PROCESSING,
    STATUS_SETTLED,
    STATUS_UNDER_INVESTIGATION,
)
from claim_agent.exceptions import InvalidClaimTransitionError

logger = logging.getLogger(__name__)

# Valid transitions: from_status -> set of to_status
# Derived from orchestrators, tools, and repository methods
_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_PENDING: frozenset({
        STATUS_PROCESSING,
        STATUS_OPEN,
        STATUS_NEEDS_REVIEW,
        STATUS_FRAUD_SUSPECTED,
    }),
    STATUS_PROCESSING: frozenset({
        STATUS_OPEN,
        STATUS_DUPLICATE,
        STATUS_SETTLED,
        STATUS_FRAUD_SUSPECTED,
        STATUS_NEEDS_REVIEW,
        STATUS_FAILED,
        STATUS_UNDER_INVESTIGATION,
    }),
    STATUS_OPEN: frozenset({
        STATUS_SETTLED,
        STATUS_DISPUTED,
        STATUS_NEEDS_REVIEW,
        STATUS_CLOSED,
        STATUS_PROCESSING,
        STATUS_DENIED,
    }),
    STATUS_NEEDS_REVIEW: frozenset({
        STATUS_PROCESSING,
        STATUS_DENIED,
        STATUS_PENDING_INFO,
        STATUS_UNDER_INVESTIGATION,
        STATUS_CLOSED,
    }),
    STATUS_DENIED: frozenset({STATUS_NEEDS_REVIEW, STATUS_CLOSED}),
    STATUS_DISPUTED: frozenset({STATUS_DISPUTE_RESOLVED, STATUS_NEEDS_REVIEW}),
    STATUS_SETTLED: frozenset({STATUS_DISPUTED, STATUS_CLOSED}),
    STATUS_UNDER_INVESTIGATION: frozenset({
        STATUS_FRAUD_SUSPECTED,
        STATUS_FRAUD_CONFIRMED,
        STATUS_NEEDS_REVIEW,
    }),
    STATUS_FRAUD_SUSPECTED: frozenset({STATUS_FRAUD_CONFIRMED, STATUS_NEEDS_REVIEW}),
    STATUS_FRAUD_CONFIRMED: frozenset({STATUS_CLOSED}),
    STATUS_DUPLICATE: frozenset({STATUS_CLOSED}),
    STATUS_FAILED: frozenset({STATUS_CLOSED, STATUS_PROCESSING}),
    STATUS_DISPUTE_RESOLVED: frozenset({STATUS_CLOSED}),
    STATUS_PENDING_INFO: frozenset({STATUS_NEEDS_REVIEW, STATUS_PROCESSING, STATUS_CLOSED}),
    STATUS_CLOSED: frozenset({STATUS_ARCHIVED}),
    STATUS_ARCHIVED: frozenset(),  # terminal
    STATUS_PARTIAL_LOSS: frozenset({STATUS_CLOSED, STATUS_SETTLED, STATUS_NEEDS_REVIEW}),
}


# Statuses that allow closing without payout (denial, duplicate, failed)
_CLOSE_WITHOUT_PAYOUT = frozenset({STATUS_DENIED, STATUS_DUPLICATE, STATUS_FAILED})


def _check_close_guard(
    claim: dict[str, Any],
    from_status: str,
    payout_amount: float | None,
) -> str | None:
    """Guard: can only close if payout is recorded, denial issued, or duplicate/failed.

    Returns error message if guard fails, None if pass.
    """
    if from_status in _CLOSE_WITHOUT_PAYOUT:
        return None
    effective_payout = payout_amount if payout_amount is not None else claim.get("payout_amount")
    if effective_payout is not None:
        return None
    return (
        "Cannot close claim without payout recorded or denial: "
        "either set payout_amount or transition from denied/duplicate/failed status"
    )


def can_transition(
    from_status: str,
    to_status: str,
    claim: dict[str, Any] | None = None,
    *,
    payout_amount: float | None = None,
    actor_id: str = "workflow",
    force: bool = False,
) -> bool:
    """Check if transition is valid (does not raise).

    Args:
        from_status: Current claim status.
        to_status: Desired new status.
        claim: Claim dict (for guards). For close transitions, the close guard is
            evaluated using claim or {} and payout_amount; when both are None, the
            guard cannot be satisfied for open/settled, so transitions from those
            statuses will fail.
        payout_amount: Optional payout being set with this transition.
        actor_id: Actor performing the transition.
        force: If True, skip validation (migrations/seeding).

    Returns:
        True if transition is allowed, False otherwise.
    """
    if force or actor_id == "system":
        return True
    if from_status not in CLAIM_STATUSES:
        return False
    if to_status not in CLAIM_STATUSES:
        return False
    if from_status == to_status:
        return True
    allowed = _TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        return False
    if to_status == STATUS_CLOSED:
        claim_dict = claim or {}
        err = _check_close_guard(claim_dict, from_status, payout_amount)
        if err:
            return False
    return True


def validate_transition(
    claim_id: str,
    from_status: str,
    to_status: str,
    claim: dict[str, Any] | None = None,
    *,
    payout_amount: float | None = None,
    actor_id: str = "workflow",
    force: bool = False,
) -> None:
    """Validate transition; raise InvalidClaimTransitionError if invalid.

    Logs transition violations for compliance alerting before raising.
    """
    if force or actor_id == "system":
        return
    if from_status not in CLAIM_STATUSES:
        reason = f"Unknown from_status: {from_status!r}"
        _log_violation(claim_id, from_status, to_status, actor_id, reason)
        raise InvalidClaimTransitionError(claim_id, from_status, to_status, reason)
    if to_status not in CLAIM_STATUSES:
        reason = f"Unknown to_status: {to_status!r}"
        _log_violation(claim_id, from_status, to_status, actor_id, reason)
        raise InvalidClaimTransitionError(claim_id, from_status, to_status, reason)
    if from_status == to_status:
        return
    allowed = _TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        reason = f"Invalid transition: {from_status!r} -> {to_status!r} (allowed: {sorted(allowed)})"
        _log_violation(claim_id, from_status, to_status, actor_id, reason)
        raise InvalidClaimTransitionError(claim_id, from_status, to_status, reason)
    if to_status == STATUS_CLOSED:
        claim_dict = claim or {}
        err = _check_close_guard(claim_dict, from_status, payout_amount)
        if err:
            _log_violation(claim_id, from_status, to_status, actor_id, err)
            raise InvalidClaimTransitionError(claim_id, from_status, to_status, err)


def _log_violation(
    claim_id: str,
    from_status: str,
    to_status: str,
    actor_id: str,
    reason: str,
) -> None:
    """Log transition violation for compliance alerting."""
    logger.warning(
        "transition_violation claim_id=%s from_status=%s to_status=%s actor_id=%s reason=%s",
        claim_id,
        from_status,
        to_status,
        actor_id,
        reason,
        extra={
            "event": "transition_violation",
            "claim_id": claim_id,
            "from_status": from_status,
            "to_status": to_status,
            "actor_id": actor_id,
            "reason": reason,
        },
    )
