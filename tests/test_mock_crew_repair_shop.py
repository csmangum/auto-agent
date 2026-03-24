"""Tests for mock repair shop: mock_notify_repair_shop and related helpers."""

import logging
from unittest.mock import patch

from claim_agent.mock_crew.repair_shop import (
    clear_all_pending_repair_shop_responses,
    get_pending_repair_shop_responses,
    mock_notify_repair_shop,
)
from claim_agent.notifications.user import notify_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_CREW_ON = {"enabled": True, "seed": None}
_MOCK_CREW_OFF = {"enabled": False, "seed": None}
_MOCK_REPAIR_SHOP_ON = {"enabled": True, "response_template": "Shop acknowledged."}
_MOCK_REPAIR_SHOP_OFF = {"enabled": False, "response_template": "Shop acknowledged."}
_MOCK_NOTIFIER_OFF = {"enabled": False, "auto_respond": False}


# ---------------------------------------------------------------------------
# Tests for mock_notify_repair_shop
# ---------------------------------------------------------------------------


class TestMockNotifyRepairShop:
    """Unit tests for mock_notify_repair_shop()."""

    def test_logs_notification_at_info(self, caplog):
        """mock_notify_repair_shop should log metadata at INFO (not full message body)."""
        with patch(
            "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
            return_value=_MOCK_REPAIR_SHOP_ON,
        ):
            with caplog.at_level(logging.INFO, logger="claim_agent.mock_crew.repair_shop"):
                mock_notify_repair_shop("CLM-R01", "Please confirm appointment.")

        assert any("CLM-R01" in m for m in caplog.messages)
        # Full message body must NOT appear in INFO records
        info_messages = [r.message for r in caplog.records if r.levelno == logging.INFO]
        assert not any("Please confirm appointment." in m for m in info_messages)

    def test_full_message_logged_at_debug(self, caplog):
        """mock_notify_repair_shop should log the message body at DEBUG level."""
        with patch(
            "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
            return_value=_MOCK_REPAIR_SHOP_ON,
        ):
            with caplog.at_level(logging.DEBUG, logger="claim_agent.mock_crew.repair_shop"):
                mock_notify_repair_shop("CLM-R02", "Sensitive repair content.")

        debug_messages = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("Sensitive repair content." in m for m in debug_messages)

    def test_acknowledgment_queued(self):
        """mock_notify_repair_shop should enqueue an acknowledgment response."""
        with patch(
            "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
            return_value=_MOCK_REPAIR_SHOP_ON,
        ):
            mock_notify_repair_shop("CLM-R03", "Authorize repair.")

        responses = get_pending_repair_shop_responses("CLM-R03")
        assert len(responses) == 1
        resp = responses[0]
        assert resp["claim_id"] == "CLM-R03"
        assert resp["original_message"] == "Authorize repair."
        assert resp["response_text"] == "Shop acknowledged."
        assert "response_id" in resp

    def test_acknowledgment_uses_config_template(self):
        """The acknowledgment text must come from response_template config."""
        custom = {"enabled": True, "response_template": "Custom shop response here."}
        with patch(
            "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
            return_value=custom,
        ):
            mock_notify_repair_shop("CLM-R04", "Authorize repair.")

        responses = get_pending_repair_shop_responses("CLM-R04")
        assert responses[0]["response_text"] == "Custom shop response here."

    def test_identifier_included_in_response(self):
        """The identifier kwarg should be stored in the queued response."""
        with patch(
            "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
            return_value=_MOCK_REPAIR_SHOP_ON,
        ):
            mock_notify_repair_shop("CLM-R05", "Check on status.", identifier="SHOP-99")

        responses = get_pending_repair_shop_responses("CLM-R05")
        assert responses[0]["identifier"] == "SHOP-99"

    def test_queue_drains_atomically(self):
        """get_pending_repair_shop_responses should clear the queue on first call."""
        with patch(
            "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
            return_value=_MOCK_REPAIR_SHOP_ON,
        ):
            mock_notify_repair_shop("CLM-R06", "First message.")

        first = get_pending_repair_shop_responses("CLM-R06")
        second = get_pending_repair_shop_responses("CLM-R06")
        assert len(first) == 1
        assert second == []

    def test_responses_isolated_by_claim_id(self):
        """Responses for different claim IDs must not bleed across."""
        with patch(
            "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
            return_value=_MOCK_REPAIR_SHOP_ON,
        ):
            mock_notify_repair_shop("CLM-R07a", "Message A.")
            mock_notify_repair_shop("CLM-R07b", "Message B.")

        assert len(get_pending_repair_shop_responses("CLM-R07a")) == 1
        assert len(get_pending_repair_shop_responses("CLM-R07b")) == 1
        assert get_pending_repair_shop_responses("CLM-R07a") == []

    def test_clear_all_pending_repair_shop_responses(self):
        """clear_all_pending_repair_shop_responses should empty all queues."""
        with patch(
            "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
            return_value=_MOCK_REPAIR_SHOP_ON,
        ):
            mock_notify_repair_shop("CLM-R08a", "Msg 1.")
            mock_notify_repair_shop("CLM-R08b", "Msg 2.")

        clear_all_pending_repair_shop_responses()
        assert get_pending_repair_shop_responses("CLM-R08a") == []
        assert get_pending_repair_shop_responses("CLM-R08b") == []


# ---------------------------------------------------------------------------
# Tests for notify_user integration (REPAIR_SHOP branch)
# ---------------------------------------------------------------------------


class TestNotifyUserRepairShopIntercept:
    """Integration tests: notify_user() repair_shop branch with mock enabled."""

    def test_notify_user_repair_shop_intercepted_when_mock_enabled(self):
        """notify_user with repair_shop type returns True and queues acknowledgment."""
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_OFF,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_repair_shop_config",
                return_value=_MOCK_REPAIR_SHOP_ON,
            ),
            patch(
                "claim_agent.mock_crew.repair_shop.get_mock_repair_shop_config",
                return_value=_MOCK_REPAIR_SHOP_ON,
            ),
        ):
            result = notify_user("repair_shop", "CLM-INT01", "Authorize repair.", identifier="SHOP-1")

        assert result is True
        responses = get_pending_repair_shop_responses("CLM-INT01")
        assert len(responses) == 1
        assert responses[0]["claim_id"] == "CLM-INT01"

    def test_notify_user_repair_shop_no_intercept_when_mock_crew_off(self, caplog):
        """notify_user with repair_shop type falls through to stub when mock crew disabled."""
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_OFF,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_OFF,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_repair_shop_config",
                return_value=_MOCK_REPAIR_SHOP_ON,
            ),
        ):
            with caplog.at_level(logging.INFO, logger="claim_agent.notifications.user"):
                result = notify_user("repair_shop", "CLM-INT02", "Authorize repair.")

        assert result is True
        # No mock repair shop response should be queued
        assert get_pending_repair_shop_responses("CLM-INT02") == []

    def test_notify_user_repair_shop_no_intercept_when_shop_mock_disabled(self, caplog):
        """notify_user falls through to stub when MOCK_REPAIR_SHOP_ENABLED=false."""
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_OFF,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_repair_shop_config",
                return_value=_MOCK_REPAIR_SHOP_OFF,
            ),
        ):
            with caplog.at_level(logging.INFO, logger="claim_agent.notifications.user"):
                result = notify_user("repair_shop", "CLM-INT03", "Authorize repair.")

        assert result is True
        assert get_pending_repair_shop_responses("CLM-INT03") == []

    def test_notify_user_repair_shop_general_notifier_takes_precedence_when_both_enabled(self):
        """When MOCK_NOTIFIER_ENABLED is also true, the general intercept runs first."""
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value={"enabled": True, "auto_respond": False},
            ),
            patch(
                "claim_agent.notifications.user.get_mock_repair_shop_config",
                return_value=_MOCK_REPAIR_SHOP_ON,
            ),
            patch("claim_agent.notifications.user.mock_notify_user") as mock_nu,
            patch("claim_agent.notifications.user.mock_notify_repair_shop") as mock_rs,
        ):
            result = notify_user("repair_shop", "CLM-INT04", "Check on status.")

        assert result is True
        mock_nu.assert_called_once()
        mock_rs.assert_not_called()
