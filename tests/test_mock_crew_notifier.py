"""Tests for mock crew notifier: mock_notify_user and get_pending_mock_responses."""

import logging
from unittest.mock import patch

import pytest

from claim_agent.mock_crew.notifier import (
    clear_all_pending_mock_responses,
    get_pending_mock_responses,
    mock_notify_user,
)
from claim_agent.notifications.user import notify_user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_CREW_ON = {"enabled": True, "seed": None}
_MOCK_CREW_OFF = {"enabled": False, "seed": None}
_MOCK_NOTIFIER_ON = {"enabled": True, "auto_respond": False}
_MOCK_NOTIFIER_AUTO = {"enabled": True, "auto_respond": True}
_MOCK_NOTIFIER_OFF = {"enabled": False, "auto_respond": False}
_MOCK_CLAIMANT_ON = {"enabled": True, "response_strategy": "immediate"}
_MOCK_CLAIMANT_OFF = {"enabled": False, "response_strategy": "immediate"}


@pytest.fixture(autouse=True)
def _clean_queue():
    """Ensure the global pending-response queue is empty before each test."""
    clear_all_pending_mock_responses()
    yield
    clear_all_pending_mock_responses()


# ---------------------------------------------------------------------------
# Tests for mock_notify_user
# ---------------------------------------------------------------------------


class TestMockNotifyUser:
    """Unit tests for mock_notify_user()."""

    def test_logs_notification_at_info(self, caplog):
        """mock_notify_user should log the notification at INFO level."""
        with patch(
            "claim_agent.mock_crew.notifier.get_mock_notifier_config",
            return_value=_MOCK_NOTIFIER_ON,
        ):
            with caplog.at_level(logging.INFO, logger="claim_agent.mock_crew.notifier"):
                mock_notify_user("claimant", "CLM-001", "Please upload photos.")

        assert any("CLM-001" in m for m in caplog.messages)
        assert any("claimant" in m for m in caplog.messages)

    def test_no_response_queued_when_auto_respond_false(self):
        """When auto_respond=False, no response should be enqueued."""
        with patch(
            "claim_agent.mock_crew.notifier.get_mock_notifier_config",
            return_value=_MOCK_NOTIFIER_ON,
        ):
            mock_notify_user("claimant", "CLM-002", "Please upload photos.")

        assert get_pending_mock_responses("CLM-002") == []

    def test_auto_respond_enqueues_response_when_claimant_enabled(self):
        """When auto_respond=True and mock claimant enabled, response is queued."""
        with (
            patch(
                "claim_agent.mock_crew.notifier.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_AUTO,
            ),
            patch(
                "claim_agent.mock_crew.notifier.get_mock_claimant_config",
                return_value=_MOCK_CLAIMANT_ON,
            ),
            patch(
                "claim_agent.mock_crew.claimant.get_mock_claimant_config",
                return_value=_MOCK_CLAIMANT_ON,
            ),
        ):
            mock_notify_user("claimant", "CLM-003", "Please upload photos.")

        responses = get_pending_mock_responses("CLM-003")
        assert len(responses) == 1
        r = responses[0]
        assert r["claim_id"] == "CLM-003"
        assert r["original_message"] == "Please upload photos."
        assert isinstance(r["response_text"], str) and r["response_text"]
        assert "response_id" in r

    def test_auto_respond_skips_when_claimant_disabled(self, caplog):
        """When auto_respond=True but mock claimant disabled, nothing is enqueued."""
        with (
            patch(
                "claim_agent.mock_crew.notifier.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_AUTO,
            ),
            patch(
                "claim_agent.mock_crew.notifier.get_mock_claimant_config",
                return_value=_MOCK_CLAIMANT_OFF,
            ),
        ):
            with caplog.at_level(logging.DEBUG, logger="claim_agent.mock_crew.notifier"):
                mock_notify_user("claimant", "CLM-004", "Provide repair estimate.")

        assert get_pending_mock_responses("CLM-004") == []

    def test_template_data_keys_logged(self, caplog):
        """Template data keys should appear in the log output."""
        with patch(
            "claim_agent.mock_crew.notifier.get_mock_notifier_config",
            return_value=_MOCK_NOTIFIER_ON,
        ):
            with caplog.at_level(logging.INFO, logger="claim_agent.mock_crew.notifier"):
                mock_notify_user(
                    "adjuster",
                    "CLM-005",
                    "Internal update.",
                    template_data={"claim_type": "partial_loss", "deadline": "2026-04-01"},
                )

        assert any("claim_type" in m or "deadline" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# Tests for get_pending_mock_responses
# ---------------------------------------------------------------------------


class TestGetPendingMockResponses:
    """Unit tests for get_pending_mock_responses()."""

    def test_returns_empty_list_when_no_responses(self):
        assert get_pending_mock_responses("CLM-UNKNOWN") == []

    def test_drains_queue_atomically(self):
        """Second call for same claim_id returns empty list."""
        with (
            patch(
                "claim_agent.mock_crew.notifier.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_AUTO,
            ),
            patch(
                "claim_agent.mock_crew.notifier.get_mock_claimant_config",
                return_value=_MOCK_CLAIMANT_ON,
            ),
            patch(
                "claim_agent.mock_crew.claimant.get_mock_claimant_config",
                return_value=_MOCK_CLAIMANT_ON,
            ),
        ):
            mock_notify_user("claimant", "CLM-010", "Any photos?")

        first = get_pending_mock_responses("CLM-010")
        second = get_pending_mock_responses("CLM-010")

        assert len(first) == 1
        assert second == []

    def test_does_not_mix_claims(self):
        """Responses for different claim IDs do not bleed into each other."""
        with (
            patch(
                "claim_agent.mock_crew.notifier.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_AUTO,
            ),
            patch(
                "claim_agent.mock_crew.notifier.get_mock_claimant_config",
                return_value=_MOCK_CLAIMANT_ON,
            ),
            patch(
                "claim_agent.mock_crew.claimant.get_mock_claimant_config",
                return_value=_MOCK_CLAIMANT_ON,
            ),
        ):
            mock_notify_user("claimant", "CLM-A", "Message A")
            mock_notify_user("claimant", "CLM-B", "Message B")

        a = get_pending_mock_responses("CLM-A")
        b = get_pending_mock_responses("CLM-B")

        assert len(a) == 1 and a[0]["claim_id"] == "CLM-A"
        assert len(b) == 1 and b[0]["claim_id"] == "CLM-B"


# ---------------------------------------------------------------------------
# Tests for notify_user intercept
# ---------------------------------------------------------------------------


class TestNotifyUserMockIntercept:
    """Integration tests: notify_user returns True without real email/SMS when mock is on."""

    def test_mock_enabled_returns_true_for_claimant(self):
        """notify_user returns True when mock crew + mock notifier enabled."""
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
        ):
            result = notify_user(
                "claimant",
                "CLM-100",
                "Please send photos.",
                email="test@example.com",
            )

        assert result is True

    def test_mock_enabled_returns_true_for_repair_shop(self):
        """notify_user returns True for repair_shop when mock is on."""
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
        ):
            result = notify_user(
                "repair_shop",
                "CLM-101",
                "Repair authorized.",
                identifier="SHOP-001",
            )

        assert result is True

    def test_mock_enabled_returns_true_without_email_or_phone(self):
        """notify_user returns True for claimant with no contact info when mock is on.

        Without the mock, claimant with no email/phone would return False.
        """
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
        ):
            result = notify_user("claimant", "CLM-102", "Missing contact info test.")

        assert result is True

    def test_mock_crew_off_does_not_intercept(self):
        """When MOCK_CREW_ENABLED=false, notify_user uses real path (not mock)."""
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_OFF,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
            patch(
                "claim_agent.notifications.user.get_notification_config",
                return_value={"email_enabled": False, "sms_enabled": False},
            ),
        ):
            # No email/SMS and not mocked → should return False (skipped)
            result = notify_user("claimant", "CLM-103", "Test without mock.")

        assert result is False

    def test_mock_notifier_off_does_not_intercept(self):
        """When MOCK_NOTIFIER_ENABLED=false, real path is used even with mock crew on."""
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
                "claim_agent.notifications.user.get_notification_config",
                return_value={"email_enabled": False, "sms_enabled": False},
            ),
        ):
            result = notify_user("claimant", "CLM-104", "Test without notifier mock.")

        assert result is False

    def test_unknown_user_type_returns_false_even_with_mock(self):
        """Unknown user_type always returns False (validated before mock check would fire)."""
        with (
            patch(
                "claim_agent.notifications.user.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.user.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
        ):
            result = notify_user("unknown_type", "CLM-105", "Should fail.")

        assert result is False


# ---------------------------------------------------------------------------
# Tests for MockNotifierConfig
# ---------------------------------------------------------------------------


class TestMockNotifierConfig:
    """Tests for MockNotifierConfig in settings."""

    def test_get_mock_notifier_config_returns_expected_keys(self):
        from claim_agent.config.settings import get_mock_notifier_config

        cfg = get_mock_notifier_config()
        assert "enabled" in cfg
        assert "auto_respond" in cfg

    def test_defaults_are_false(self):
        from claim_agent.config.settings import get_mock_notifier_config

        cfg = get_mock_notifier_config()
        assert cfg["enabled"] is False
        assert cfg["auto_respond"] is False

    def test_env_override_enabled(self):
        import os

        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_mock_notifier_config

        with patch.dict(os.environ, {"MOCK_NOTIFIER_ENABLED": "true"}):
            reload_settings()
            cfg = get_mock_notifier_config()
            assert cfg["enabled"] is True

        reload_settings()

    def test_env_override_auto_respond(self):
        import os

        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_mock_notifier_config

        with patch.dict(os.environ, {"MOCK_NOTIFIER_AUTO_RESPOND": "true"}):
            reload_settings()
            cfg = get_mock_notifier_config()
            assert cfg["auto_respond"] is True

        reload_settings()
