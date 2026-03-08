"""Tests for claim event emission and listener invocation."""

from unittest.mock import MagicMock

import pytest

from claim_agent.events import (
    ClaimEvent,
    emit_claim_event,
    register_claim_event_listener,
    unregister_claim_event_listener,
)


class TestClaimEvent:
    """Tests for ClaimEvent dataclass."""

    def test_required_fields(self):
        event = ClaimEvent(claim_id="CLM-123", status="pending")
        assert event.claim_id == "CLM-123"
        assert event.status == "pending"
        assert event.summary is None
        assert event.claim_type is None
        assert event.payout_amount is None

    def test_optional_fields(self):
        event = ClaimEvent(
            claim_id="CLM-456",
            status="settled",
            summary="Settled",
            claim_type="partial_loss",
            payout_amount=2500.0,
        )
        assert event.summary == "Settled"
        assert event.claim_type == "partial_loss"
        assert event.payout_amount == 2500.0


class TestEmitClaimEvent:
    """Tests for emit_claim_event and listener registration."""

    def test_emits_to_registered_listener(self):
        received: list[ClaimEvent] = []
        listener = lambda e: received.append(e)
        register_claim_event_listener(listener)
        try:
            event = ClaimEvent(claim_id="CLM-789", status="processing", summary="Started")
            emit_claim_event(event)
            assert len(received) == 1
            assert received[0].claim_id == "CLM-789"
            assert received[0].status == "processing"
            assert received[0].summary == "Started"
        finally:
            unregister_claim_event_listener(listener)

    def test_swallows_listener_exceptions(self):
        mock = MagicMock(side_effect=RuntimeError("listener failed"))
        register_claim_event_listener(mock)
        try:
            emit_claim_event(ClaimEvent(claim_id="CLM-X", status="pending"))
            mock.assert_called_once()
        finally:
            unregister_claim_event_listener(mock)
