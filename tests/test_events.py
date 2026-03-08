"""Tests for claim event emission and listener invocation."""

from unittest.mock import MagicMock, patch

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

    @pytest.fixture(autouse=True)
    def _isolate_webhook(self):
        """Patch webhook config so event tests do not trigger real webhook delivery."""
        disabled_config = {"enabled": False, "urls": []}
        with patch(
            "claim_agent.notifications.webhook.get_webhook_config",
            return_value=disabled_config,
        ):
            yield

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

    def test_failing_listener_does_not_block_others(self):
        """When one listener throws, other listeners still receive the event."""
        received: list[ClaimEvent] = []
        good_listener = lambda e: received.append(e)
        bad_listener = MagicMock(side_effect=RuntimeError("listener failed"))

        register_claim_event_listener(bad_listener)
        register_claim_event_listener(good_listener)
        try:
            event = ClaimEvent(claim_id="CLM-Y", status="settled", summary="Done")
            emit_claim_event(event)
            assert len(received) == 1
            assert received[0].claim_id == "CLM-Y"
            bad_listener.assert_called_once()
        finally:
            unregister_claim_event_listener(bad_listener)
            unregister_claim_event_listener(good_listener)
