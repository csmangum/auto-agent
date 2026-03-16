"""Unit tests for ClaimStateMachine."""

import pytest

from claim_agent.db.constants import (
    STATUS_CLOSED,
    STATUS_DENIED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_OPEN,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_SETTLED,
)
from claim_agent.db.state_machine import can_transition, validate_transition
from claim_agent.exceptions import InvalidClaimTransitionError


class TestCanTransition:
    """Tests for can_transition (non-raising check)."""

    def test_same_status_idempotent(self):
        assert can_transition(STATUS_OPEN, STATUS_OPEN) is True
        assert can_transition(STATUS_PENDING, STATUS_PENDING) is True

    def test_valid_transitions(self):
        assert can_transition(STATUS_PENDING, STATUS_PROCESSING) is True
        assert can_transition(STATUS_PROCESSING, STATUS_OPEN) is True
        assert can_transition(STATUS_PROCESSING, STATUS_NEEDS_REVIEW) is True
        assert can_transition(STATUS_NEEDS_REVIEW, STATUS_DENIED) is True
        assert can_transition(STATUS_NEEDS_REVIEW, STATUS_PROCESSING) is True
        assert can_transition(STATUS_DENIED, STATUS_NEEDS_REVIEW) is True
        assert can_transition(STATUS_OPEN, STATUS_CLOSED, claim={"payout_amount": 1000.0}) is True

    def test_invalid_transitions(self):
        assert can_transition(STATUS_CLOSED, STATUS_OPEN) is False
        assert can_transition(STATUS_DENIED, STATUS_SETTLED) is False
        assert can_transition(STATUS_PENDING, STATUS_CLOSED) is False

    def test_close_guard_without_payout_from_open_fails(self):
        assert can_transition(STATUS_OPEN, STATUS_CLOSED, claim={}) is False
        assert can_transition(STATUS_OPEN, STATUS_CLOSED, claim={"payout_amount": None}) is False

    def test_close_guard_with_payout_passes(self):
        assert can_transition(STATUS_OPEN, STATUS_CLOSED, claim={"payout_amount": 0.0}) is True
        assert can_transition(STATUS_OPEN, STATUS_CLOSED, payout_amount=500.0) is True

    def test_close_from_denied_without_payout_passes(self):
        assert can_transition(STATUS_DENIED, STATUS_CLOSED, claim={}) is True

    def test_close_from_duplicate_without_payout_passes(self):
        assert can_transition(STATUS_DUPLICATE, STATUS_CLOSED, claim={}) is True

    def test_close_from_failed_without_payout_passes(self):
        assert can_transition(STATUS_FAILED, STATUS_CLOSED, claim={}) is True

    def test_force_bypasses_validation(self):
        assert can_transition(STATUS_CLOSED, STATUS_OPEN, force=True) is True

    def test_system_actor_bypasses_validation(self):
        assert can_transition(STATUS_CLOSED, STATUS_OPEN, actor_id="system") is True

    def test_unknown_status_rejected(self):
        assert can_transition("invalid", STATUS_OPEN) is False
        assert can_transition(STATUS_OPEN, "invalid") is False


class TestValidateTransition:
    """Tests for validate_transition (raises on invalid)."""

    def test_valid_transition_passes(self):
        validate_transition("CLM-1", STATUS_PENDING, STATUS_PROCESSING)
        validate_transition("CLM-1", STATUS_OPEN, STATUS_CLOSED, claim={"payout_amount": 100.0})

    def test_same_status_passes(self):
        validate_transition("CLM-1", STATUS_OPEN, STATUS_OPEN)

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidClaimTransitionError) as exc_info:
            validate_transition("CLM-1", STATUS_CLOSED, STATUS_OPEN)
        assert exc_info.value.claim_id == "CLM-1"
        assert exc_info.value.from_status == STATUS_CLOSED
        assert exc_info.value.to_status == STATUS_OPEN

    def test_denied_to_settled_raises(self):
        with pytest.raises(InvalidClaimTransitionError):
            validate_transition("CLM-1", STATUS_DENIED, STATUS_SETTLED)

    def test_close_without_payout_from_open_raises(self):
        with pytest.raises(InvalidClaimTransitionError):
            validate_transition("CLM-1", STATUS_OPEN, STATUS_CLOSED, claim={})

    def test_force_bypasses_validation(self):
        validate_transition("CLM-1", STATUS_CLOSED, STATUS_OPEN, force=True)
