"""Tests for mock webhook: capture_webhook, get_captured_webhooks, dispatch_webhook integration."""

import logging
from unittest.mock import patch

from claim_agent.mock_crew.webhook import (
    capture_webhook,
    clear_captured_webhooks,
    get_captured_webhooks,
)
from claim_agent.notifications.webhook import dispatch_repair_authorized, dispatch_webhook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_CREW_ON = {"enabled": True, "seed": None}
_MOCK_CREW_OFF = {"enabled": False, "seed": None}
_MOCK_WEBHOOK_CAPTURE_ON = {"capture_enabled": True}
_MOCK_WEBHOOK_CAPTURE_OFF = {"capture_enabled": False}


# ---------------------------------------------------------------------------
# Tests for capture_webhook / get_captured_webhooks
# ---------------------------------------------------------------------------


class TestCaptureWebhook:
    """Unit tests for the in-memory capture store."""

    def test_capture_stores_payload(self):
        """capture_webhook should store the payload in the in-memory list."""
        payload = {"event": "claim.submitted", "claim_id": "CLM-W01"}
        capture_webhook("claim.submitted", payload)

        captured = get_captured_webhooks()
        assert len(captured) == 1
        assert captured[0]["claim_id"] == "CLM-W01"
        assert captured[0]["event"] == "claim.submitted"

    def test_get_captured_webhooks_filters_by_event(self):
        """get_captured_webhooks(event=...) should return only matching entries."""
        capture_webhook("claim.submitted", {"event": "claim.submitted", "claim_id": "CLM-W02a"})
        capture_webhook("claim.closed", {"event": "claim.closed", "claim_id": "CLM-W02b"})

        submitted = get_captured_webhooks(event="claim.submitted")
        closed = get_captured_webhooks(event="claim.closed")

        assert len(submitted) == 1
        assert submitted[0]["claim_id"] == "CLM-W02a"
        assert len(closed) == 1
        assert closed[0]["claim_id"] == "CLM-W02b"

    def test_get_captured_webhooks_no_filter_returns_all(self):
        """get_captured_webhooks() without event returns all captured payloads."""
        capture_webhook("claim.submitted", {"event": "claim.submitted", "claim_id": "CLM-W03a"})
        capture_webhook("repair.authorized", {"event": "repair.authorized", "claim_id": "CLM-W03b"})

        all_events = get_captured_webhooks()
        assert len(all_events) == 2

    def test_get_captured_webhooks_does_not_drain_list(self):
        """get_captured_webhooks should not remove entries (non-destructive)."""
        capture_webhook("claim.submitted", {"event": "claim.submitted", "claim_id": "CLM-W04"})

        first = get_captured_webhooks()
        second = get_captured_webhooks()
        assert len(first) == 1
        assert len(second) == 1

    def test_clear_captured_webhooks_empties_list(self):
        """clear_captured_webhooks should remove all captured payloads."""
        capture_webhook("claim.submitted", {"event": "claim.submitted", "claim_id": "CLM-W05a"})
        capture_webhook("claim.closed", {"event": "claim.closed", "claim_id": "CLM-W05b"})

        clear_captured_webhooks()
        assert get_captured_webhooks() == []

    def test_capture_stores_copy_of_payload(self):
        """Captured payloads should be independent copies (mutations do not affect store)."""
        payload = {"event": "claim.submitted", "claim_id": "CLM-W06", "extra": "original"}
        capture_webhook("claim.submitted", payload)
        payload["extra"] = "mutated"

        captured = get_captured_webhooks()
        assert captured[0]["extra"] == "original"

    def test_get_captured_returns_copy(self):
        """Modifying the returned list should not affect the internal store."""
        capture_webhook("claim.submitted", {"event": "claim.submitted", "claim_id": "CLM-W07"})

        result = get_captured_webhooks()
        result.clear()

        assert len(get_captured_webhooks()) == 1

    def test_logs_capture_at_info(self, caplog):
        """capture_webhook should log at INFO level."""
        with caplog.at_level(logging.INFO, logger="claim_agent.mock_crew.webhook"):
            capture_webhook("claim.submitted", {"event": "claim.submitted", "claim_id": "CLM-W08"})

        assert any("CLM-W08" in m for m in caplog.messages)
        assert any("claim.submitted" in m for m in caplog.messages)

    def test_get_captured_webhooks_returns_empty_list_when_no_match(self):
        """get_captured_webhooks(event='nonexistent') should return empty list."""
        capture_webhook("claim.submitted", {"event": "claim.submitted", "claim_id": "CLM-W09"})
        assert get_captured_webhooks(event="nonexistent.event") == []


# ---------------------------------------------------------------------------
# Tests for dispatch_webhook integration
# ---------------------------------------------------------------------------


class TestDispatchWebhookMockIntegration:
    """Integration tests: dispatch_webhook with mock webhook capture enabled."""

    def test_dispatch_webhook_captured_when_mock_enabled(self):
        """dispatch_webhook appends to capture list and makes no HTTP call."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_ON,
            ),
        ):
            dispatch_webhook("claim.submitted", {"claim_id": "CLM-DW01"})

        captured = get_captured_webhooks(event="claim.submitted")
        assert len(captured) == 1
        assert captured[0]["claim_id"] == "CLM-DW01"
        assert captured[0]["event"] == "claim.submitted"
        assert "timestamp" in captured[0]

    def test_dispatch_webhook_capture_disabled_does_not_capture(self):
        """When capture_enabled=false, dispatch_webhook does not capture payloads."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_OFF,
            ),
            patch("claim_agent.notifications.webhook.get_webhook_config") as mock_wh_cfg,
        ):
            mock_wh_cfg.return_value = {"enabled": False, "urls": []}
            dispatch_webhook("claim.submitted", {"claim_id": "CLM-DW02"})

        assert get_captured_webhooks() == []

    def test_dispatch_webhook_mock_crew_off_does_not_capture(self):
        """When MOCK_CREW_ENABLED=false, no capture occurs even if capture_enabled=true."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_OFF,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_ON,
            ),
            patch("claim_agent.notifications.webhook.get_webhook_config") as mock_wh_cfg,
        ):
            mock_wh_cfg.return_value = {"enabled": False, "urls": []}
            dispatch_webhook("claim.submitted", {"claim_id": "CLM-DW03"})

        assert get_captured_webhooks() == []

    def test_multiple_dispatch_all_captured(self):
        """All dispatched webhooks are captured in order."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_ON,
            ),
        ):
            dispatch_webhook("claim.submitted", {"claim_id": "CLM-DW04a"})
            dispatch_webhook("claim.closed", {"claim_id": "CLM-DW04b"})

        all_events = get_captured_webhooks()
        assert len(all_events) == 2
        events = {e["event"] for e in all_events}
        assert "claim.submitted" in events
        assert "claim.closed" in events

    def test_dispatch_webhook_capture_includes_timestamp(self):
        """Captured payload must include the timestamp added by dispatch_webhook."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_ON,
            ),
        ):
            dispatch_webhook("claim.submitted", {"claim_id": "CLM-DW05"})

        captured = get_captured_webhooks()
        assert "timestamp" in captured[0]


# ---------------------------------------------------------------------------
# Tests for dispatch_repair_authorized with mock webhook capture
# ---------------------------------------------------------------------------


_WEBHOOK_CONFIG_WITH_SHOP = {
    "enabled": True,
    "urls": ["https://example.com/hook"],
    "secret": "",
    "max_retries": 0,
    "dead_letter_path": None,
    "shop_url": "https://shop.example.com/hook",
}


class TestDispatchRepairAuthorizedMockIntegration:
    """Integration tests: dispatch_repair_authorized shop-specific POST."""

    def test_shop_specific_post_captured_when_mock_enabled(self):
        """Shop-specific POST should be captured, not delivered via HTTP."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_webhook_config",
                return_value=_WEBHOOK_CONFIG_WITH_SHOP,
            ),
        ):
            dispatch_repair_authorized(
                claim_id="CLM-RA01",
                shop_id="SHOP-001",
                shop_name="Quality Auto",
                shop_phone="555-1234",
                authorized_amount=2500.0,
                authorization_id="RA-001",
            )

        captured = get_captured_webhooks(event="repair.authorized")
        assert len(captured) == 2
        claim_ids = [c["claim_id"] for c in captured]
        assert all(cid == "CLM-RA01" for cid in claim_ids)

    def test_shop_url_post_captured_when_explicit_url(self):
        """Explicit shop_webhook_url should also be captured by mock."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_webhook_config",
                return_value={**_WEBHOOK_CONFIG_WITH_SHOP, "shop_url": None},
            ),
        ):
            dispatch_repair_authorized(
                claim_id="CLM-RA02",
                shop_id="SHOP-002",
                shop_name="Fast Fix",
                shop_phone="555-5678",
                authorized_amount=1800.0,
                authorization_id="RA-002",
                shop_webhook_url="https://fastfix.example.com/hook",
            )

        captured = get_captured_webhooks(event="repair.authorized")
        assert len(captured) == 2

    def test_no_shop_url_captures_only_general_webhook(self):
        """Without shop URL, only the general dispatch_webhook capture fires."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_ON,
            ),
            patch(
                "claim_agent.notifications.webhook.get_webhook_config",
                return_value={**_WEBHOOK_CONFIG_WITH_SHOP, "shop_url": None},
            ),
        ):
            dispatch_repair_authorized(
                claim_id="CLM-RA03",
                shop_id="SHOP-003",
                shop_name="No Shop URL",
                shop_phone="555-0000",
                authorized_amount=900.0,
                authorization_id="RA-003",
            )

        captured = get_captured_webhooks(event="repair.authorized")
        assert len(captured) == 1
        assert captured[0]["claim_id"] == "CLM-RA03"
