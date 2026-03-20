"""Unit tests for ClaimStateMachine."""

import pytest

from claim_agent.db.constants import (
    STATUS_ARCHIVED,
    STATUS_CLOSED,
    STATUS_DENIED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_OPEN,
    STATUS_PENDING,
    STATUS_PENDING_INFO,
    STATUS_PROCESSING,
    STATUS_PURGED,
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

    def test_archived_to_purged_allowed(self):
        assert can_transition(STATUS_ARCHIVED, STATUS_PURGED) is True

    def test_purged_is_terminal(self):
        assert can_transition(STATUS_PURGED, STATUS_CLOSED) is False

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

    def test_open_to_pending_info_blocked_without_bi_type(self):
        assert can_transition(STATUS_OPEN, STATUS_PENDING_INFO, claim={"claim_type": "partial_loss"}) is False
        assert can_transition(STATUS_OPEN, STATUS_PENDING_INFO, claim={}) is False

    def test_open_to_pending_info_allowed_for_bodily_injury(self):
        assert (
            can_transition(
                STATUS_OPEN,
                STATUS_PENDING_INFO,
                claim={"claim_type": "bodily_injury"},
            )
            is True
        )
        assert (
            can_transition(STATUS_OPEN, STATUS_PENDING_INFO, claim={}, claim_type="bodily_injury") is True
        )

    def test_partial_loss_settlement_guard_when_flag_false(self):
        claim = {"claim_type": "partial_loss", "repair_ready_for_settlement": False}
        assert can_transition(STATUS_OPEN, STATUS_SETTLED, claim=claim) is False

    def test_partial_loss_settlement_allowed_when_flag_true(self):
        claim = {"claim_type": "partial_loss", "repair_ready_for_settlement": True}
        assert can_transition(STATUS_OPEN, STATUS_SETTLED, claim=claim) is True

    def test_partial_loss_settlement_allowed_when_flag_absent(self):
        claim = {"claim_type": "partial_loss"}
        assert can_transition(STATUS_OPEN, STATUS_SETTLED, claim=claim) is True

    def test_total_loss_settlement_guard_when_flag_false(self):
        claim = {"claim_type": "total_loss", "total_loss_settlement_authorized": False}
        assert can_transition(STATUS_OPEN, STATUS_SETTLED, claim=claim) is False

    def test_explicit_claim_type_overrides_claim_dict_type(self):
        """Explicit claim_type= arg takes precedence over claim["claim_type"]."""
        non_bi_claim = {"claim_type": "partial_loss"}
        assert (
            can_transition(
                STATUS_OPEN,
                STATUS_PENDING_INFO,
                claim=non_bi_claim,
                claim_type="bodily_injury",
            )
            is True
        )

    def test_explicit_non_bi_overrides_bi_in_claim_dict(self):
        """Explicit non-BI claim_type should block open -> pending_info even if claim is BI."""
        bi_claim = {"claim_type": "bodily_injury"}
        assert (
            can_transition(
                STATUS_OPEN,
                STATUS_PENDING_INFO,
                claim=bi_claim,
                claim_type="partial_loss",
            )
            is False
        )


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

    def test_bi_open_to_pending_info_validates(self):
        validate_transition(
            "CLM-bi",
            STATUS_OPEN,
            STATUS_PENDING_INFO,
            claim={"claim_type": "bodily_injury"},
        )

    def test_partial_loss_settlement_guard_raises(self):
        claim = {"claim_type": "partial_loss", "repair_ready_for_settlement": False}
        with pytest.raises(InvalidClaimTransitionError) as exc:
            validate_transition("CLM-pl", STATUS_OPEN, STATUS_SETTLED, claim=claim)
        assert "partial_loss" in exc.value.reason.lower()

    def test_total_loss_settlement_guard_raises(self):
        claim = {"claim_type": "total_loss", "total_loss_settlement_authorized": False}
        with pytest.raises(InvalidClaimTransitionError) as exc:
            validate_transition("CLM-tl", STATUS_OPEN, STATUS_SETTLED, claim=claim)
        assert "total_loss" in exc.value.reason.lower()

    def test_explicit_bi_overrides_non_bi_claim_type(self):
        """Explicit claim_type='bodily_injury' should allow open -> pending_info even if claim says otherwise."""
        non_bi_claim = {"claim_type": "property_damage"}
        validate_transition(
            "CLM-bi-override",
            STATUS_OPEN,
            STATUS_PENDING_INFO,
            claim=non_bi_claim,
            claim_type="bodily_injury",
        )

    def test_explicit_non_bi_overrides_bi_claim_type_and_fails(self):
        """Explicit non-BI claim_type should block open -> pending_info even if claim is BI."""
        bi_claim = {"claim_type": "bodily_injury"}
        with pytest.raises(InvalidClaimTransitionError):
            validate_transition(
                "CLM-nonbi-override",
                STATUS_OPEN,
                STATUS_PENDING_INFO,
                claim=bi_claim,
                claim_type="property_damage",
            )
