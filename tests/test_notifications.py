"""Tests for webhooks and claimant notifications."""

import hashlib
import hmac
import logging
import os
import tempfile
from unittest.mock import patch

from sqlalchemy import text

from claim_agent.config import reload_settings
from claim_agent.config.settings import get_notification_config, get_webhook_config
from tests.conftest import LogCaptureHandler
from claim_agent.notifications.claimant import notify_claimant
from claim_agent.notifications.webhook import (
    _sign_payload,
    dispatch_claim_event,
    dispatch_repair_authorized,
    dispatch_webhook,
    safe_dispatch_claim_event,
)


def _claimant_executor_submit_inline(fn, *args, **kwargs):
    """Run claimant notification work inline so tests do not race ThreadPoolExecutor."""
    fn(*args, **kwargs)


class TestWebhookConfig:
    """Tests for get_webhook_config."""

    def test_returns_dict_with_expected_keys(self):
        config = get_webhook_config()
        assert isinstance(config, dict)
        assert "urls" in config
        assert "secret" in config
        assert "max_retries" in config
        assert "enabled" in config

    def test_urls_from_webhook_url(self):
        with patch.dict(os.environ, {"WEBHOOK_URL": "https://example.com/hook", "WEBHOOK_URLS": ""}):
            reload_settings()
            config = get_webhook_config()
            assert config["urls"] == ["https://example.com/hook"]

    def test_urls_from_webhook_urls_comma_separated(self):
        with patch.dict(
            os.environ,
            {"WEBHOOK_URLS": "https://a.com/hook, https://b.com/hook", "WEBHOOK_URL": ""},
        ):
            reload_settings()
            config = get_webhook_config()
            assert config["urls"] == ["https://a.com/hook", "https://b.com/hook"]

    def test_max_retries_default(self):
        with patch.dict(os.environ, {}, clear=False):
            config = get_webhook_config()
            assert config["max_retries"] == 5

    def test_max_retries_override(self):
        with patch.dict(os.environ, {"WEBHOOK_MAX_RETRIES": "3"}):
            reload_settings()
            config = get_webhook_config()
            assert config["max_retries"] == 3

    def test_enabled_default(self):
        with patch.dict(os.environ, {}, clear=False):
            config = get_webhook_config()
            assert config["enabled"] is True

    def test_enabled_false(self):
        with patch.dict(os.environ, {"WEBHOOK_ENABLED": "false"}):
            reload_settings()
            config = get_webhook_config()
            assert config["enabled"] is False


class TestWebhookSigning:
    """Tests for HMAC signature."""

    def test_sign_payload_empty_secret_returns_empty(self):
        assert _sign_payload("", b'{"a":1}') == ""

    def test_sign_payload_produces_hex_digest(self):
        sig = _sign_payload("secret", b'{"claim_id":"CLM-123"}')
        assert isinstance(sig, str)
        assert len(sig) == 64
        assert all(c in "0123456789abcdef" for c in sig)

    def test_sign_payload_deterministic(self):
        body = b'{"claim_id":"CLM-123"}'
        assert _sign_payload("secret", body) == _sign_payload("secret", body)

    def test_sign_payload_verifiable(self):
        secret = "my-secret"
        body = b'{"event":"claim.submitted","claim_id":"CLM-ABC"}'
        sig = _sign_payload(secret, body)
        expected = hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
        assert sig == expected


class TestDispatchClaimEvent:
    """Tests for dispatch_claim_event event mapping."""

    def test_pending_maps_to_submitted(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_claim_event("CLM-123", "pending")
                mock.assert_called_once()
                event, payload = mock.call_args[0]
                assert event == "claim.submitted"
                assert payload["claim_id"] == "CLM-123"
                assert payload["status"] == "pending"

    def test_processing_maps_to_processing(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_claim_event("CLM-123", "processing", summary="Started")
                mock.assert_called_once()
                event, payload = mock.call_args[0]
                assert event == "claim.processing"
                assert payload["summary"] == "Started"

    def test_needs_review_maps_to_needs_review(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_claim_event("CLM-123", "needs_review")
                assert mock.call_args[0][0] == "claim.needs_review"

    def test_failed_maps_to_failed(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_claim_event("CLM-123", "failed")
                assert mock.call_args[0][0] == "claim.failed"

    def test_open_maps_to_opened(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_claim_event("CLM-123", "open", summary="Claim opened for claimant")
                mock.assert_called_once()
                event, payload = mock.call_args[0]
                assert event == "claim.opened"
                assert payload["status"] == "open"

    def test_settled_maps_to_closed(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_claim_event(
                    "CLM-123",
                    "settled",
                    claim_type="partial_loss",
                    payout_amount=2500.0,
                )
                event, payload = mock.call_args[0]
                assert event == "claim.closed"
                assert payload["claim_type"] == "partial_loss"
                assert payload["payout_amount"] == 2500.0

    def test_archived_maps_to_claim_archived(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_claim_event(
                    "CLM-123",
                    "archived",
                    summary="Archived for retention",
                    claim_type="partial_loss",
                    payout_amount=1500.0,
                )
                event, payload = mock.call_args[0]
                assert event == "claim.archived"
                assert payload["status"] == "archived"
                assert payload["summary"] == "Archived for retention"
                assert payload["claim_type"] == "partial_loss"
                assert payload["payout_amount"] == 1500.0

    def test_purged_maps_to_claim_purged(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_claim_event(
                    "CLM-123",
                    "purged",
                    summary="Purged for retention",
                    claim_type="partial_loss",
                    payout_amount=1500.0,
                )
                event, payload = mock.call_args[0]
                assert event == "claim.purged"
                assert payload["status"] == "purged"
                assert payload["summary"] == "Purged for retention"


class TestSafeDispatchClaimEvent:
    """Tests for safe_dispatch_claim_event best-effort behavior."""

    def test_swallows_exceptions_and_logs(self):
        webhook_logger = logging.getLogger("claim_agent.notifications.webhook")
        cap = LogCaptureHandler()
        webhook_logger.addHandler(cap)
        webhook_logger.setLevel(logging.WARNING)
        try:
            with patch("claim_agent.notifications.webhook.dispatch_claim_event") as mock:
                mock.side_effect = RuntimeError("executor shutdown")
                safe_dispatch_claim_event("CLM-123", "pending", summary="Test")
                mock.assert_called_once()
        finally:
            webhook_logger.removeHandler(cap)
        assert any("Webhook dispatch failed" in m for m in cap.messages)
        assert any("executor shutdown" in m for m in cap.messages)

    def test_delegates_to_dispatch_claim_event_on_success(self):
        with patch("claim_agent.notifications.webhook.dispatch_claim_event") as mock:
            safe_dispatch_claim_event("CLM-123", "pending", summary="Test")
            mock.assert_called_once()
            assert mock.call_args[0][0] == "CLM-123"
            assert mock.call_args[0][1] == "pending"
            assert mock.call_args[1]["summary"] == "Test"


class TestDispatchWebhook:
    """Tests for dispatch_webhook delivery."""

    def test_disabled_does_not_deliver(self):
        with patch("claim_agent.notifications.webhook._EXECUTOR") as mock_exec:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "false"},
            ):
                dispatch_webhook("claim.submitted", {"claim_id": "CLM-123"})
                mock_exec.submit.assert_not_called()

    def test_no_urls_does_not_deliver(self):
        with patch("claim_agent.notifications.webhook._EXECUTOR") as mock_exec:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "", "WEBHOOK_URLS": "", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_webhook("claim.submitted", {"claim_id": "CLM-123"})
                mock_exec.submit.assert_not_called()

    def test_delivers_when_enabled_and_url_configured(self):
        submitted = []

        def run_sync(fn):
            submitted.append(fn)
            fn()

        with patch("claim_agent.notifications.webhook._EXECUTOR") as mock_exec:
            mock_exec.submit.side_effect = run_sync
            with patch("claim_agent.notifications.webhook._deliver_one") as mock_deliver:
                with patch.dict(
                    os.environ,
                    {
                        "WEBHOOK_URL": "https://example.com/webhook",
                        "WEBHOOK_ENABLED": "true",
                        "WEBHOOK_SECRET": "test-secret",
                    },
                ):
                    reload_settings()
                    dispatch_webhook("claim.submitted", {"claim_id": "CLM-ABC"})
                    mock_deliver.assert_called_once()
                    assert mock_deliver.call_args[0][0] == "https://example.com/webhook"
                    payload = mock_deliver.call_args[0][1]
                    assert payload["event"] == "claim.submitted"
                    assert payload["claim_id"] == "CLM-ABC"
                    assert "timestamp" in payload


class TestDispatchRepairAuthorized:
    """Tests for dispatch_repair_authorized."""

    def test_dispatches_repair_authorized_event(self):
        with patch("claim_agent.notifications.webhook.dispatch_webhook") as mock:
            with patch.dict(
                os.environ,
                {"WEBHOOK_URL": "https://x.com/hook", "WEBHOOK_ENABLED": "true"},
            ):
                dispatch_repair_authorized(
                    claim_id="CLM-123",
                    shop_id="SHOP-001",
                    shop_name="Premier Auto",
                    shop_phone="555-0100",
                    authorized_amount=3500.0,
                    authorization_id="RA-ABCD1234",
                )
                mock.assert_called_once()
                event, payload = mock.call_args[0]
                assert event == "repair.authorized"
                assert payload["claim_id"] == "CLM-123"
                assert payload["shop_id"] == "SHOP-001"
                assert payload["authorized_amount"] == 3500.0
                assert payload["authorization_id"] == "RA-ABCD1234"


class TestNotificationConfig:
    """Tests for get_notification_config."""

    def test_returns_dict(self):
        config = get_notification_config()
        assert isinstance(config, dict)
        assert "email_enabled" in config
        assert "sms_enabled" in config
        assert "sendgrid_api_key" in config
        assert "sendgrid_from_email" in config
        assert "twilio_account_sid" in config
        assert "twilio_auth_token" in config
        assert "twilio_from_phone" in config
        assert isinstance(config["sendgrid_api_key"], str)
        assert isinstance(config["twilio_auth_token"], str)

    def test_default_disabled(self):
        with patch.dict(os.environ, {}, clear=False):
            config = get_notification_config()
            assert config["email_enabled"] is False
            assert config["sms_enabled"] is False


class TestNotifyClaimant:
    """Tests for claimant notifications."""

    def test_opt_out_skips(self, caplog):
        with patch.dict(os.environ, {"NOTIFICATION_EMAIL_ENABLED": "true"}):
            notify_claimant("receipt_acknowledged", "CLM-123", email="a@b.com", opt_out=True)
        assert "Would send" not in caplog.text

    def test_no_contact_skips(self, caplog):
        with patch.dict(os.environ, {"NOTIFICATION_EMAIL_ENABLED": "true"}):
            notify_claimant("receipt_acknowledged", "CLM-123")
        assert "Would send" not in caplog.text

    def test_sends_email_when_enabled_and_contact_present(self):
        claimant_logger = logging.getLogger("claim_agent.notifications.claimant")
        cap = LogCaptureHandler()
        claimant_logger.addHandler(cap)
        claimant_logger.setLevel(logging.INFO)
        try:
            with patch("claim_agent.notifications.claimant._EXECUTOR") as mock_exec:
                mock_exec.submit.side_effect = _claimant_executor_submit_inline
                with patch("claim_agent.notifications.claimant.httpx.Client") as mock_client_cls:
                    mock_client = mock_client_cls.return_value.__enter__.return_value
                    mock_client.post.return_value.status_code = 202
                    with patch.dict(
                        os.environ,
                        {
                            "NOTIFICATION_EMAIL_ENABLED": "true",
                            "SENDGRID_API_KEY": "sg-key",
                            "SENDGRID_FROM_EMAIL": "noreply@example.com",
                        },
                    ):
                        reload_settings()
                        notify_claimant("receipt_acknowledged", "CLM-123", email="a@b.com")
                    mock_client.post.assert_called_once()
                    assert mock_client.post.call_args[0][0] == "https://api.sendgrid.com/v3/mail/send"
        finally:
            claimant_logger.removeHandler(cap)
        assert any("Sent claimant email" in m for m in cap.messages)
        assert any("receipt_acknowledged" in m for m in cap.messages)
        assert any("CLM-123" in m for m in cap.messages)

    def test_sends_sms_when_enabled_and_phone_present(self):
        claimant_logger = logging.getLogger("claim_agent.notifications.claimant")
        cap = LogCaptureHandler()
        claimant_logger.addHandler(cap)
        claimant_logger.setLevel(logging.INFO)
        try:
            with patch("claim_agent.notifications.claimant._EXECUTOR") as mock_exec:
                mock_exec.submit.side_effect = _claimant_executor_submit_inline
                with patch("claim_agent.notifications.claimant.httpx.Client") as mock_client_cls:
                    mock_client = mock_client_cls.return_value.__enter__.return_value
                    mock_client.post.return_value.status_code = 201
                    with patch.dict(
                        os.environ,
                        {
                            "NOTIFICATION_SMS_ENABLED": "true",
                            "TWILIO_ACCOUNT_SID": "sid",
                            "TWILIO_AUTH_TOKEN": "token",
                            "TWILIO_FROM_PHONE": "+15550000000",
                        },
                    ):
                        reload_settings()
                        notify_claimant("claim_closed", "CLM-456", phone="+15551234567")
                    mock_client.post.assert_called_once()
                    assert (
                        mock_client.post.call_args[0][0]
                        == "https://api.twilio.com/2010-04-01/Accounts/sid/Messages.json"
                    )
        finally:
            claimant_logger.removeHandler(cap)
        assert any("Sent claimant SMS" in m for m in cap.messages)
        assert any("claim_closed" in m for m in cap.messages)

    def test_warns_when_email_enabled_but_provider_credentials_missing(self):
        claimant_logger = logging.getLogger("claim_agent.notifications.claimant")
        cap = LogCaptureHandler()
        claimant_logger.addHandler(cap)
        claimant_logger.setLevel(logging.WARNING)
        try:
            with patch("claim_agent.notifications.claimant._EXECUTOR") as mock_exec:
                mock_exec.submit.side_effect = _claimant_executor_submit_inline
                with patch.dict(os.environ, {"NOTIFICATION_EMAIL_ENABLED": "true"}):
                    reload_settings()
                    notify_claimant("receipt_acknowledged", "CLM-123", email="a@b.com")
        finally:
            claimant_logger.removeHandler(cap)
        assert any("provider credentials missing" in m for m in cap.messages)


class TestRepositoryWebhookIntegration:
    """Tests that repository emits claim events (which trigger webhooks via listener)."""

    def test_create_claim_emits_submitted(self):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.events import ClaimEvent
        from claim_agent.models.claim import ClaimInput

        with patch("claim_agent.db.repository.emit_claim_event") as mock:
            repo = ClaimRepository()
            claim_input = ClaimInput(
                policy_number="POL-001",
                vin="1HGBH41JXMN109186",
                vehicle_year=2021,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date="2025-01-15",
                incident_description="Rear-ended.",
                damage_description="Bumper damage.",
            )
            claim_id = repo.create_claim(claim_input)
            mock.assert_called_once()
            event = mock.call_args[0][0]
            assert isinstance(event, ClaimEvent)
            assert event.claim_id == claim_id
            assert event.status == "pending"

    def test_update_claim_status_emits_event(self):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.events import ClaimEvent
        from claim_agent.models.claim import ClaimInput

        repo = ClaimRepository()
        claim_input = ClaimInput(
            policy_number="POL-002",
            vin="2HGBH41JXMN109187",
            vehicle_year=2020,
            vehicle_make="Toyota",
            vehicle_model="Camry",
            incident_date="2025-02-01",
            incident_description="Fender bender.",
            damage_description="Scratch on door.",
        )
        claim_id = repo.create_claim(claim_input)

        with patch("claim_agent.db.repository.emit_claim_event") as mock:
            mock.reset_mock()
            repo.update_claim_status(claim_id, "processing", details="Started")
            mock.assert_called_once()
            event = mock.call_args[0][0]
            assert isinstance(event, ClaimEvent)
            assert event.claim_id == claim_id
            assert event.status == "processing"

    def test_archive_claim_emits_archived(self):
        from claim_agent.db.database import get_connection, init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.events import ClaimEvent
        from claim_agent.models.claim import ClaimInput

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            claim_input = ClaimInput(
                policy_number="POL-003",
                vin="3HGBH41JXMN109188",
                vehicle_year=2019,
                vehicle_make="Honda",
                vehicle_model="Accord",
                incident_date="2019-06-01",
                incident_description="Test",
                damage_description="Test",
            )
            claim_id = repo.create_claim(claim_input)
            from claim_agent.db.constants import STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING

            repo.update_claim_status(claim_id, STATUS_PROCESSING, skip_validation=True)
            repo.update_claim_status(claim_id, STATUS_OPEN, skip_validation=True)
            repo.update_claim_status(
                claim_id, STATUS_CLOSED, payout_amount=0.0, skip_validation=True
            )
            with get_connection(db_path) as conn:
                conn.execute(
                    text("UPDATE claims SET created_at = datetime('now', '-10 years') WHERE id = :id"),
                    {"id": claim_id},
                )

            with patch("claim_agent.db.repository.emit_claim_event") as mock:
                repo.archive_claim(claim_id)
                mock.assert_called_once()
                event = mock.call_args[0][0]
                assert isinstance(event, ClaimEvent)
                assert event.claim_id == claim_id
                assert event.status == "archived"
                assert event.summary == "Archived for retention"
        finally:
            os.unlink(db_path)

    def test_purge_claim_emits_purged(self):
        from claim_agent.db.constants import STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING
        from claim_agent.db.database import get_connection, init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.events import ClaimEvent
        from claim_agent.models.claim import ClaimInput

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            init_db(db_path)
            repo = ClaimRepository(db_path=db_path)
            claim_input = ClaimInput(
                policy_number="POL-PURGE",
                vin="3HGBH41JXMN109199",
                vehicle_year=2019,
                vehicle_make="Honda",
                vehicle_model="Accord",
                incident_date="2019-06-01",
                incident_description="Test",
                damage_description="Test",
            )
            claim_id = repo.create_claim(claim_input)
            repo.update_claim_status(claim_id, STATUS_PROCESSING, skip_validation=True)
            repo.update_claim_status(claim_id, STATUS_OPEN, skip_validation=True)
            repo.update_claim_status(
                claim_id, STATUS_CLOSED, payout_amount=0.0, skip_validation=True
            )
            repo.archive_claim(claim_id)
            with get_connection(db_path) as conn:
                conn.execute(
                    text(
                        "UPDATE claims SET archived_at = datetime('now', '-5 years') "
                        "WHERE id = :id"
                    ),
                    {"id": claim_id},
                )
            with patch("claim_agent.db.repository.emit_claim_event") as mock:
                repo.purge_claim(claim_id)
                mock.assert_called_once()
                event = mock.call_args[0][0]
                assert isinstance(event, ClaimEvent)
                assert event.claim_id == claim_id
                assert event.status == "purged"
                assert event.summary == "Purged for retention"
        finally:
            os.unlink(db_path)
