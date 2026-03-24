"""Tests for mock crew notifier: mock_notify_user and get_pending_mock_responses."""

import logging
from unittest.mock import patch

import pytest

from claim_agent.mock_crew.notifier import (
    clear_all_pending_mock_responses,
    get_pending_mock_responses,
    mock_notify_user,
)
from claim_agent.notifications.claimant import notify_claimant, send_otp_notification
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
        """mock_notify_user should log metadata at INFO level (not full message body)."""
        with patch(
            "claim_agent.mock_crew.notifier.get_mock_notifier_config",
            return_value=_MOCK_NOTIFIER_ON,
        ):
            with caplog.at_level(logging.INFO, logger="claim_agent.mock_crew.notifier"):
                mock_notify_user("claimant", "CLM-001", "Please upload photos.")

        # Metadata is present at INFO
        assert any("CLM-001" in m for m in caplog.messages)
        assert any("claimant" in m for m in caplog.messages)
        # Full message body must NOT appear in INFO records
        info_messages = [
            r.message for r in caplog.records if r.levelno == logging.INFO
        ]
        assert not any("Please upload photos." in m for m in info_messages)

    def test_full_message_logged_at_debug(self, caplog):
        """mock_notify_user should log the message body at DEBUG level."""
        with patch(
            "claim_agent.mock_crew.notifier.get_mock_notifier_config",
            return_value=_MOCK_NOTIFIER_ON,
        ):
            with caplog.at_level(logging.DEBUG, logger="claim_agent.mock_crew.notifier"):
                mock_notify_user("claimant", "CLM-001b", "Sensitive content here.")

        debug_messages = [
            r.message for r in caplog.records if r.levelno == logging.DEBUG
        ]
        assert any("Sensitive content here." in m for m in debug_messages)

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

    def test_auto_respond_skips_for_non_claimant_user_types(self):
        """auto_respond should not enqueue responses for adjuster/repair_shop/siu."""
        with (
            patch(
                "claim_agent.mock_crew.notifier.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_AUTO,
            ),
            patch(
                "claim_agent.mock_crew.notifier.get_mock_claimant_config",
                return_value=_MOCK_CLAIMANT_ON,
            ),
        ):
            mock_notify_user("adjuster", "CLM-006", "Internal adjuster note.")
            mock_notify_user("repair_shop", "CLM-007", "Repair authorization.")
            mock_notify_user("siu", "CLM-008", "SIU referral.")

        assert get_pending_mock_responses("CLM-006") == []
        assert get_pending_mock_responses("CLM-007") == []
        assert get_pending_mock_responses("CLM-008") == []

    def test_auto_respond_enqueues_for_claimant_facing_types(self):
        """auto_respond should queue responses for all claimant-facing user types."""
        claimant_types = ["claimant", "policyholder", "witness", "attorney"]
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
            for i, ut in enumerate(claimant_types):
                mock_notify_user(ut, f"CLM-09{i}", "Please upload photos.")

        for i, ut in enumerate(claimant_types):
            responses = get_pending_mock_responses(f"CLM-09{i}")
            assert len(responses) == 1, f"Expected 1 response for user_type={ut}"

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


# ---------------------------------------------------------------------------
# Tests for notify_claimant intercept
# ---------------------------------------------------------------------------


class TestNotifyClaimantMockIntercept:
    """Tests: notify_claimant is suppressed under mock crew + mock notifier."""

    def test_notify_claimant_suppressed_when_mock_enabled(self):
        """notify_claimant should not submit email/SMS jobs when mock is active."""
        with (
            patch(
                "claim_agent.notifications.claimant.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.claimant.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
            patch("claim_agent.notifications.claimant._EXECUTOR") as mock_exec,
        ):
            notify_claimant(
                "receipt_acknowledged",
                "CLM-200",
                email="test@example.com",
            )

            # Executor must not have been called (no real email/SMS submitted)
            mock_exec.submit.assert_not_called()

    def test_notify_claimant_real_path_when_mock_off(self):
        """notify_claimant uses the real path when mock is disabled."""
        with (
            patch(
                "claim_agent.notifications.claimant.get_mock_crew_config",
                return_value=_MOCK_CREW_OFF,
            ),
            patch(
                "claim_agent.notifications.claimant.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
            patch(
                "claim_agent.notifications.claimant.get_notification_config",
                return_value={"email_enabled": True, "sms_enabled": False,
                              "sendgrid_api_key": "key", "sendgrid_from_email": "from@x.com",
                              "twilio_account_sid": "", "twilio_auth_token": "",
                              "twilio_from_phone": ""},
            ),
            patch("claim_agent.notifications.claimant._EXECUTOR") as mock_exec,
        ):
            notify_claimant(
                "receipt_acknowledged",
                "CLM-201",
                email="test@example.com",
            )

            mock_exec.submit.assert_called_once()

    def test_notify_claimant_suppressed_without_contact_info(self):
        """Mock intercept fires even when email and phone are both None."""
        with (
            patch(
                "claim_agent.notifications.claimant.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.claimant.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
            patch(
                "claim_agent.notifications.claimant.mock_notify_claimant",
            ) as mock_fn,
            patch("claim_agent.notifications.claimant._EXECUTOR") as mock_exec,
        ):
            notify_claimant("receipt_acknowledged", "CLM-210")

            mock_fn.assert_called_once_with("receipt_acknowledged", "CLM-210")
            mock_exec.submit.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for send_otp_notification intercept
# ---------------------------------------------------------------------------


class TestSendOtpNotificationMockIntercept:
    """Tests: send_otp_notification is suppressed under mock crew + mock notifier."""

    def test_otp_notification_suppressed_when_mock_enabled(self, caplog):
        """send_otp_notification should not attempt real delivery when mock is active."""
        with (
            patch(
                "claim_agent.notifications.claimant.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.notifications.claimant.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
            patch("claim_agent.notifications.claimant._send_email") as mock_email,
            patch("claim_agent.notifications.claimant._send_sms") as mock_sms,
        ):
            with caplog.at_level(logging.INFO, logger="claim_agent.notifications.claimant"):
                send_otp_notification("user@example.com", "email", "123456", "VER-001")

            mock_email.assert_not_called()
            mock_sms.assert_not_called()

        assert any("OTP notification suppressed" in m for m in caplog.messages)

    def test_otp_notification_real_path_when_mock_off(self):
        """send_otp_notification uses the real path when mock is disabled."""
        with (
            patch(
                "claim_agent.notifications.claimant.get_mock_crew_config",
                return_value=_MOCK_CREW_OFF,
            ),
            patch(
                "claim_agent.notifications.claimant.get_mock_notifier_config",
                return_value=_MOCK_NOTIFIER_ON,
            ),
            patch(
                "claim_agent.notifications.claimant.get_notification_config",
                return_value={"email_enabled": True, "sms_enabled": False,
                              "sendgrid_api_key": "key", "sendgrid_from_email": "from@x.com",
                              "twilio_account_sid": "", "twilio_auth_token": "",
                              "twilio_from_phone": ""},
            ),
            patch("claim_agent.notifications.claimant._send_email") as mock_email,
        ):
            send_otp_notification("user@example.com", "email", "123456", "VER-002")

            mock_email.assert_called_once()


# ---------------------------------------------------------------------------
# Tests for clear_all_pending_mock_responses
# ---------------------------------------------------------------------------


class TestClearAllPendingMockResponses:
    """Explicit tests for clear_all_pending_mock_responses()."""

    def test_clears_queued_responses(self):
        """Queued responses are removed after clear_all_pending_mock_responses()."""
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
            mock_notify_user("claimant", "CLM-300", "Need photos.")
            mock_notify_user("claimant", "CLM-301", "Need estimate.")

        assert get_pending_mock_responses("CLM-300") != []
        clear_all_pending_mock_responses()
        assert get_pending_mock_responses("CLM-301") == []

    def test_clear_is_idempotent(self):
        """Calling clear on an already-empty queue does not raise."""
        clear_all_pending_mock_responses()
        clear_all_pending_mock_responses()
