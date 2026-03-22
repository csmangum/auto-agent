"""Tests for DSAR OTP claimant verification service."""

from __future__ import annotations

import pytest

from claim_agent.config import reload_settings
from claim_agent.db.database import get_connection, init_db
from claim_agent.services.dsar_verification import (
    CHANNEL_EMAIL,
    CHANNEL_SMS,
    DSAR_AUDIT_OTP_FAILED,
    DSAR_AUDIT_OTP_RATE_LIMITED,
    DSAR_AUDIT_OTP_REQUESTED,
    DSAR_AUDIT_OTP_VERIFIED,
    RateLimitExceeded,
    _generate_otp,
    _hash_otp,
    _make_salt,
    _otp_rate_limit_time_predicate,
    claimant_identifiers_match,
    get_verification_token,
    is_verified,
    request_otp,
    verify_otp,
)
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def otp_db(tmp_path):
    """Temporary SQLite DB with all tables including dsar_verification_tokens."""
    db_path = str(tmp_path / "otp_test.db")
    init_db(db_path)
    return db_path


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


class TestOTPRateLimitSQL:
    def test_sqlite_predicate_uses_datetime(self):
        assert "datetime(created_at)" in _otp_rate_limit_time_predicate("sqlite")

    def test_postgresql_predicate_uses_timestamptz(self):
        pred = _otp_rate_limit_time_predicate("postgresql")
        assert "created_at >=" in pred
        assert "TIMESTAMP WITH TIME ZONE" in pred


class TestClaimantIdentifiersMatch:
    def test_email_case_insensitive(self):
        assert claimant_identifiers_match("A@B.C", "a@b.c", CHANNEL_EMAIL)
        assert not claimant_identifiers_match("a@b.c", "x@y.z", CHANNEL_EMAIL)

    def test_sms_digits_normalize(self):
        assert claimant_identifiers_match("+1 (555) 000-1234", "15550001234", CHANNEL_SMS)
        assert not claimant_identifiers_match("+15550001234", "+15559999999", CHANNEL_SMS)


class TestOTPHelpers:
    def test_generate_otp_length(self):
        otp = _generate_otp(6)
        assert len(otp) == 6
        assert otp.isdigit()

    def test_generate_otp_custom_length(self):
        otp = _generate_otp(8)
        assert len(otp) == 8

    def test_hash_otp_deterministic(self):
        otp = "123456"
        salt = _make_salt()
        h1 = _hash_otp(otp, salt)
        h2 = _hash_otp(otp, salt)
        assert h1 == h2

    def test_hash_otp_different_salt(self):
        otp = "123456"
        h1 = _hash_otp(otp, _make_salt())
        h2 = _hash_otp(otp, _make_salt())
        # Different salts → different hashes (astronomically unlikely to collide)
        assert h1 != h2

    def test_salt_uniqueness(self):
        s1 = _make_salt()
        s2 = _make_salt()
        assert s1 != s2


# ---------------------------------------------------------------------------
# request_otp()
# ---------------------------------------------------------------------------


class TestRequestOTP:
    def test_request_otp_email_returns_verification_id(self, otp_db, monkeypatch):
        monkeypatch.setattr(
            "claim_agent.services.dsar_verification._deliver_otp",
            lambda *a, **kw: None,
        )
        vid = request_otp("user@example.com", CHANNEL_EMAIL, db_path=otp_db)
        assert vid
        token = get_verification_token(vid, db_path=otp_db)
        assert token is not None
        assert token["claimant_identifier"] == "user@example.com"
        assert token["channel"] == CHANNEL_EMAIL
        assert token["verified_at"] is None
        assert token["attempts"] == 0

    def test_request_otp_sms_channel(self, otp_db, monkeypatch):
        monkeypatch.setattr(
            "claim_agent.services.dsar_verification._deliver_otp",
            lambda *a, **kw: None,
        )
        vid = request_otp("+15005550006", CHANNEL_SMS, db_path=otp_db)
        token = get_verification_token(vid, db_path=otp_db)
        assert token["channel"] == CHANNEL_SMS

    def test_request_otp_invalid_channel_raises(self, otp_db):
        with pytest.raises(ValueError, match="Invalid channel"):
            request_otp("user@example.com", "fax", db_path=otp_db)

    def test_request_otp_creates_audit_entry(self, otp_db, monkeypatch):
        monkeypatch.setattr(
            "claim_agent.services.dsar_verification._deliver_otp",
            lambda *a, **kw: None,
        )
        vid = request_otp("audit@example.com", CHANNEL_EMAIL, db_path=otp_db)
        with get_connection(otp_db) as conn:
            row = conn.execute(
                text(
                    "SELECT action, actor_id FROM dsar_audit_log "
                    "WHERE request_id = :vid AND action = :action"
                ),
                {"vid": vid, "action": DSAR_AUDIT_OTP_REQUESTED},
            ).fetchone()
        assert row is not None
        assert row[0] == DSAR_AUDIT_OTP_REQUESTED
        assert row[1] == "audit@example.com"

    def test_request_otp_rate_limit(self, otp_db, monkeypatch):
        """Exceeding OTP_RATE_LIMIT_MAX_REQUESTS raises RateLimitExceeded."""
        monkeypatch.setenv("OTP_RATE_LIMIT_MAX_REQUESTS", "2")
        reload_settings()
        monkeypatch.setattr(
            "claim_agent.services.dsar_verification._deliver_otp",
            lambda *a, **kw: None,
        )

        request_otp("rate@example.com", CHANNEL_EMAIL, db_path=otp_db)
        request_otp("rate@example.com", CHANNEL_EMAIL, db_path=otp_db)
        with pytest.raises(RateLimitExceeded, match="Rate limit exceeded"):
            request_otp("rate@example.com", CHANNEL_EMAIL, db_path=otp_db)

    def test_request_otp_rate_limit_creates_audit_entry(self, otp_db, monkeypatch):
        monkeypatch.setenv("OTP_RATE_LIMIT_MAX_REQUESTS", "1")
        reload_settings()
        monkeypatch.setattr(
            "claim_agent.services.dsar_verification._deliver_otp",
            lambda *a, **kw: None,
        )

        request_otp("rl2@example.com", CHANNEL_EMAIL, db_path=otp_db)
        with pytest.raises(RateLimitExceeded):
            request_otp("rl2@example.com", CHANNEL_EMAIL, db_path=otp_db)

        with get_connection(otp_db) as conn:
            row = conn.execute(
                text(
                    "SELECT action FROM dsar_audit_log "
                    "WHERE actor_id = 'rl2@example.com' AND action = :action"
                ),
                {"action": DSAR_AUDIT_OTP_RATE_LIMITED},
            ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# verify_otp()
# ---------------------------------------------------------------------------


class TestVerifyOTP:
    def _insert_token(self, db_path, *, otp, identifier="v@example.com", channel="email",
                      expires_offset_min=15, already_verified=False):
        """Helper: insert a token row directly so we can control the OTP value."""
        from datetime import timedelta

        salt = _make_salt()
        token_hash = _hash_otp(otp, salt)
        vid = str(__import__("uuid").uuid4())
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(minutes=expires_offset_min)).isoformat()
        verified_at = now.isoformat() if already_verified else None

        with get_connection(db_path) as conn:
            conn.execute(
                text("""
                    INSERT INTO dsar_verification_tokens
                        (verification_id, claimant_identifier, channel,
                         token_hash, salt, expires_at, verified_at)
                    VALUES (:vid, :identifier, :channel, :token_hash, :salt, :expires_at, :verified_at)
                """),
                {
                    "vid": vid,
                    "identifier": identifier,
                    "channel": channel,
                    "token_hash": token_hash,
                    "salt": salt,
                    "expires_at": expires_at,
                    "verified_at": verified_at,
                },
            )
        return vid

    def test_correct_code_succeeds(self, otp_db):
        otp = "987654"
        vid = self._insert_token(otp_db, otp=otp)
        result = verify_otp(vid, otp, db_path=otp_db)
        assert result["verified"] is True
        assert "successfully" in result["message"].lower()

    def test_correct_code_marks_verified_at(self, otp_db):
        otp = "111111"
        vid = self._insert_token(otp_db, otp=otp)
        verify_otp(vid, otp, db_path=otp_db)
        token = get_verification_token(vid, db_path=otp_db)
        assert token["verified_at"] is not None

    def test_wrong_code_fails(self, otp_db):
        otp = "222222"
        vid = self._insert_token(otp_db, otp=otp)
        result = verify_otp(vid, "000000", db_path=otp_db)
        assert result["verified"] is False
        assert "Invalid" in result["message"]

    def test_wrong_code_increments_attempts(self, otp_db):
        otp = "333333"
        vid = self._insert_token(otp_db, otp=otp)
        verify_otp(vid, "000000", db_path=otp_db)
        token = get_verification_token(vid, db_path=otp_db)
        assert token["attempts"] == 1

    def test_wrong_code_creates_failed_audit_entry(self, otp_db):
        otp = "444444"
        vid = self._insert_token(otp_db, otp=otp)
        verify_otp(vid, "000000", db_path=otp_db)
        with get_connection(otp_db) as conn:
            row = conn.execute(
                text(
                    "SELECT action FROM dsar_audit_log "
                    "WHERE request_id = :vid AND action = :action"
                ),
                {"vid": vid, "action": DSAR_AUDIT_OTP_FAILED},
            ).fetchone()
        assert row is not None

    def test_success_creates_verified_audit_entry(self, otp_db):
        otp = "555555"
        vid = self._insert_token(otp_db, otp=otp)
        verify_otp(vid, otp, db_path=otp_db)
        with get_connection(otp_db) as conn:
            row = conn.execute(
                text(
                    "SELECT action FROM dsar_audit_log "
                    "WHERE request_id = :vid AND action = :action"
                ),
                {"vid": vid, "action": DSAR_AUDIT_OTP_VERIFIED},
            ).fetchone()
        assert row is not None

    def test_already_verified_returns_already_used(self, otp_db):
        otp = "666666"
        vid = self._insert_token(otp_db, otp=otp, already_verified=True)
        result = verify_otp(vid, otp, db_path=otp_db)
        assert result["verified"] is False
        assert "already been used" in result["message"]

    def test_expired_token_fails(self, otp_db):
        otp = "777777"
        vid = self._insert_token(otp_db, otp=otp, expires_offset_min=-1)
        result = verify_otp(vid, otp, db_path=otp_db)
        assert result["verified"] is False
        assert "expired" in result["message"]

    def test_expired_creates_failed_audit_entry(self, otp_db):
        otp = "888888"
        vid = self._insert_token(otp_db, otp=otp, expires_offset_min=-1)
        verify_otp(vid, otp, db_path=otp_db)
        with get_connection(otp_db) as conn:
            row = conn.execute(
                text(
                    "SELECT action FROM dsar_audit_log "
                    "WHERE request_id = :vid AND action = :action"
                ),
                {"vid": vid, "action": DSAR_AUDIT_OTP_FAILED},
            ).fetchone()
        assert row is not None

    def test_unknown_verification_id_raises(self, otp_db):
        with pytest.raises(ValueError, match="not found"):
            verify_otp("nonexistent-id", "000000", db_path=otp_db)

    def test_max_attempts_locks_token(self, otp_db, monkeypatch):
        monkeypatch.setenv("OTP_MAX_ATTEMPTS", "2")
        reload_settings()

        otp = "999999"
        vid = self._insert_token(otp_db, otp=otp)
        verify_otp(vid, "000000", db_path=otp_db)
        verify_otp(vid, "000000", db_path=otp_db)
        # Third attempt: token is locked
        result = verify_otp(vid, "000000", db_path=otp_db)
        assert result["verified"] is False
        assert "Too many" in result["message"]


# ---------------------------------------------------------------------------
# is_verified() and get_verification_token()
# ---------------------------------------------------------------------------


class TestIsVerified:
    def _make_verified_token(self, db_path):
        otp = "121212"
        from datetime import datetime, timedelta, timezone

        salt = _make_salt()
        token_hash = _hash_otp(otp, salt)
        vid = str(__import__("uuid").uuid4())
        now = datetime.now(timezone.utc)
        expires_at = (now + timedelta(minutes=15)).isoformat()
        verified_at = now.isoformat()

        with get_connection(db_path) as conn:
            conn.execute(
                text("""
                    INSERT INTO dsar_verification_tokens
                        (verification_id, claimant_identifier, channel,
                         token_hash, salt, expires_at, verified_at)
                    VALUES (:vid, :id, :ch, :th, :salt, :ea, :va)
                """),
                {
                    "vid": vid,
                    "id": "v@example.com",
                    "ch": "email",
                    "th": token_hash,
                    "salt": salt,
                    "ea": expires_at,
                    "va": verified_at,
                },
            )
        return vid

    def test_is_verified_true_for_verified_token(self, otp_db):
        vid = self._make_verified_token(otp_db)
        assert is_verified(vid, db_path=otp_db) is True

    def test_is_verified_false_for_unknown_id(self, otp_db):
        assert is_verified("unknown-id", db_path=otp_db) is False

    def test_is_verified_false_for_unverified_token(self, otp_db, monkeypatch):
        monkeypatch.setattr(
            "claim_agent.services.dsar_verification._deliver_otp",
            lambda *a, **kw: None,
        )
        vid = request_otp("unverified@example.com", CHANNEL_EMAIL, db_path=otp_db)
        assert is_verified(vid, db_path=otp_db) is False

    def test_get_verification_token_no_hash_or_salt(self, otp_db, monkeypatch):
        monkeypatch.setattr(
            "claim_agent.services.dsar_verification._deliver_otp",
            lambda *a, **kw: None,
        )
        vid = request_otp("safe@example.com", CHANNEL_EMAIL, db_path=otp_db)
        token = get_verification_token(vid, db_path=otp_db)
        assert token is not None
        assert "token_hash" not in token
        assert "salt" not in token

    def test_get_verification_token_returns_none_for_unknown(self, otp_db):
        assert get_verification_token("no-such-id", db_path=otp_db) is None


# ---------------------------------------------------------------------------
# OTP notification delivery (unit-level, mocked)
# ---------------------------------------------------------------------------


class TestOTPNotificationDelivery:
    def test_send_otp_notification_email_disabled_logs_warning(self, caplog, monkeypatch):
        """send_otp_notification logs a warning when email is disabled."""
        monkeypatch.setenv("NOTIFICATION_EMAIL_ENABLED", "false")
        reload_settings()
        from claim_agent.notifications.claimant import send_otp_notification

        with caplog.at_level("WARNING", logger="claim_agent.notifications.claimant"):
            send_otp_notification("x@example.com", "email", "123456", "vid-1")
        assert "disabled" in caplog.text.lower()

    def test_send_otp_notification_sms_disabled_logs_warning(self, caplog, monkeypatch):
        monkeypatch.setenv("NOTIFICATION_SMS_ENABLED", "false")
        reload_settings()
        from claim_agent.notifications.claimant import send_otp_notification

        with caplog.at_level("WARNING", logger="claim_agent.notifications.claimant"):
            send_otp_notification("+15005550006", "sms", "654321", "vid-2")
        assert "disabled" in caplog.text.lower()

    def test_send_otp_notification_unknown_channel_logs_warning(self, caplog, monkeypatch):
        from claim_agent.notifications.claimant import send_otp_notification

        with caplog.at_level("WARNING", logger="claim_agent.notifications.claimant"):
            send_otp_notification("x@example.com", "fax", "000000", "vid-3")
        assert "unknown channel" in caplog.text.lower()


# ---------------------------------------------------------------------------
# Full round-trip: request → verify → is_verified
# ---------------------------------------------------------------------------


class TestFullRoundTrip:
    def test_full_otp_flow(self, otp_db, monkeypatch):
        """End-to-end: request OTP → capture OTP → verify → is_verified."""
        captured: list[str] = []

        def fake_deliver(identifier, channel, otp, vid):
            captured.append(otp)

        monkeypatch.setattr(
            "claim_agent.services.dsar_verification._deliver_otp",
            fake_deliver,
        )

        vid = request_otp("roundtrip@example.com", CHANNEL_EMAIL, db_path=otp_db)
        assert captured, "OTP should have been captured"

        result = verify_otp(vid, captured[0], db_path=otp_db)
        assert result["verified"] is True

        assert is_verified(vid, db_path=otp_db) is True
