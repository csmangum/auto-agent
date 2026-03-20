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
    STATUS_PENDING: frozenset(
        {
            STATUS_PROCESSING,
            STATUS_OPEN,
            STATUS_NEEDS_REVIEW,
            STATUS_FRAUD_SUSPECTED,
        }
    ),
    STATUS_PROCESSING: frozenset(
        {
            STATUS_OPEN,
            STATUS_DUPLICATE,
            STATUS_DENIED,
            STATUS_SETTLED,
            STATUS_FRAUD_SUSPECTED,
            STATUS_NEEDS_REVIEW,
            STATUS_FAILED,
            STATUS_UNDER_INVESTIGATION,
        }
    ),
    STATUS_OPEN: frozenset(
        {
            STATUS_SETTLED,
            STATUS_DISPUTED,
            STATUS_NEEDS_REVIEW,
            STATUS_CLOSED,
            STATUS_PROCESSING,
            STATUS_DENIED,
        }
    ),
    STATUS_NEEDS_REVIEW: frozenset(
        {
            STATUS_PROCESSING,
            STATUS_DENIED,
            STATUS_PENDING_INFO,
            STATUS_UNDER_INVESTIGATION,
            STATUS_CLOSED,
        }
    ),
    STATUS_DENIED: frozenset({STATUS_NEEDS_REVIEW, STATUS_CLOSED}),
    STATUS_DISPUTED: frozenset({STATUS_DISPUTE_RESOLVED, STATUS_NEEDS_REVIEW}),
    STATUS_SETTLED: frozenset({STATUS_DISPUTED, STATUS_CLOSED}),
    STATUS_UNDER_INVESTIGATION: frozenset(
        {
            STATUS_FRAUD_SUSPECTED,
            STATUS_FRAUD_CONFIRMED,
            STATUS_NEEDS_REVIEW,
        }
    ),
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

# Extra allowed targets per (claim_type, from_status). Merged with _TRANSITIONS.
_CLAIM_TYPE_TRANSITION_ADDITIONS: dict[str, dict[str, frozenset[str]]] = {
    # Ongoing treatment / documentation before settlement or closure
    "bodily_injury": {
        STATUS_OPEN: frozenset({STATUS_PENDING_INFO}),
    },
}


def _normalize_claim_type(raw: str | None) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip().lower()
    return s or None


def _resolve_claim_type(
    claim: dict[str, Any] | None,
    claim_type: str | None,
) -> str | None:
    """Effective claim type for variant rules: explicit param wins, else claim.claim_type."""
    explicit = _normalize_claim_type(claim_type)
    if explicit is not None:
        return explicit
    return _normalize_claim_type((claim or {}).get("claim_type"))


def _allowed_targets(
    from_status: str,
    *,
    claim_type: str | None,
) -> frozenset[str]:
    base = _TRANSITIONS.get(from_status, frozenset())
    if not claim_type or claim_type not in _CLAIM_TYPE_TRANSITION_ADDITIONS:
        return base
    extra = _CLAIM_TYPE_TRANSITION_ADDITIONS[claim_type].get(from_status, frozenset())
    if not extra:
        return base
    return frozenset(base | extra)


def _falsy_workflow_flag(val: Any) -> bool:
    """True when a persisted 0/False should block settlement (DB may use INTEGER 0)."""
    return val is False or val == 0


def _type_specific_guard(
    from_status: str,
    to_status: str,
    claim: dict[str, Any],
    claim_type: str | None,
) -> str | None:
    """Optional gates when claim dict carries explicit workflow flags (backward compatible)."""
    if not claim_type:
        return None
    if claim_type == "partial_loss" and from_status == STATUS_OPEN and to_status == STATUS_SETTLED:
        if "repair_ready_for_settlement" in claim and _falsy_workflow_flag(
            claim.get("repair_ready_for_settlement")
        ):
            return "partial_loss: cannot move open -> settled while repair_ready_for_settlement is false"
    if claim_type == "total_loss" and from_status == STATUS_OPEN and to_status == STATUS_SETTLED:
        if "total_loss_settlement_authorized" in claim and _falsy_workflow_flag(
            claim.get("total_loss_settlement_authorized")
        ):
            return "total_loss: cannot move open -> settled while total_loss_settlement_authorized is false"
    return None


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
    claim_type: str | None = None,
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
        claim_type: Optional claim type for per-type rules; overrides claim["claim_type"].
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
    ct = _resolve_claim_type(claim, claim_type)
    allowed = _allowed_targets(from_status, claim_type=ct)
    if to_status not in allowed:
        return False
    claim_dict = claim or {}
    err_guard = _type_specific_guard(from_status, to_status, claim_dict, ct)
    if err_guard:
        return False
    if to_status == STATUS_CLOSED:
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
    claim_type: str | None = None,
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
    ct = _resolve_claim_type(claim, claim_type)
    allowed = _allowed_targets(from_status, claim_type=ct)
    if to_status not in allowed:
        reason = (
            f"Invalid transition: {from_status!r} -> {to_status!r} (allowed: {sorted(allowed)})"
        )
        _log_violation(claim_id, from_status, to_status, actor_id, reason)
        raise InvalidClaimTransitionError(claim_id, from_status, to_status, reason)
    claim_dict = claim or {}
    err_guard = _type_specific_guard(from_status, to_status, claim_dict, ct)
    if err_guard:
        _log_violation(claim_id, from_status, to_status, actor_id, err_guard)
        raise InvalidClaimTransitionError(claim_id, from_status, to_status, err_guard)
    if to_status == STATUS_CLOSED:
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
