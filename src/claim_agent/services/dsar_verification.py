"""DSAR claimant verification service - OTP generation, delivery, and validation.

Provides a self-service identity-proofing flow for DSAR requests:
  1. request_otp()  – generate a one-time password, deliver it via email or SMS,
                      return a ``verification_id`` for tracking.
  2. verify_otp()   – validate the submitted code; mark token as used on success.
  3. is_verified()  – check whether a token was successfully verified and is still
                      within its TTL (use before fulfilling a DSAR request).

Rate limiting is enforced at the service layer (N requests per identifier per hour).
All attempts are recorded in ``dsar_audit_log`` for audit-trail purposes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.notifications.claimant import send_otp_notification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHANNEL_EMAIL = "email"
CHANNEL_SMS = "sms"
VALID_CHANNELS = (CHANNEL_EMAIL, CHANNEL_SMS)

DSAR_AUDIT_OTP_REQUESTED = "otp_requested"
DSAR_AUDIT_OTP_VERIFIED = "otp_verified"
DSAR_AUDIT_OTP_FAILED = "otp_failed"
DSAR_AUDIT_OTP_RATE_LIMITED = "otp_rate_limited"


class RateLimitExceeded(Exception):
    """Raised when OTP request rate limit is exceeded for a claimant identifier."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _otp_rate_limit_time_predicate(dialect_name: str) -> str:
    """SQL fragment comparing token ``created_at`` to the rate-limit window start."""
    if dialect_name == "sqlite":
        return "datetime(created_at) >= datetime(:window_start)"
    return "created_at >= CAST(:window_start AS TIMESTAMP WITH TIME ZONE)"


def _digits_only(value: str | None) -> str:
    if not value:
        return ""
    return "".join(c for c in value if c.isdigit())


def claimant_identifiers_match(stored: str, submitted: str, channel: str) -> bool:
    """Return True when *submitted* matches the OTP token's stored identifier for *channel*."""
    if channel == CHANNEL_EMAIL:
        return stored.strip().lower() == submitted.strip().lower()
    if channel == CHANNEL_SMS:
        ds, dj = _digits_only(stored), _digits_only(submitted)
        return bool(ds) and ds == dj
    return False


def _generate_otp(length: int = 6) -> str:
    """Return a cryptographically strong random numeric OTP of *length* digits."""
    upper = 10**length
    return str(secrets.randbelow(upper)).zfill(length)


def _make_salt() -> str:
    """Return a fresh random hex salt."""
    return uuid.uuid4().hex


def _hash_otp(otp: str, salt: str) -> str:
    """Return HMAC-SHA256 of *salt*:*otp* keyed with a server-side pepper (hex digest).

    The pepper is read from ``PrivacyConfig.otp_pepper`` (env: ``OTP_PEPPER``), falling
    back to ``settings.auth.jwt_secret`` when the dedicated pepper is not set.  Using a
    server-side secret means that even if the database is fully compromised an attacker
    cannot brute-force 6-digit OTPs offline without also knowing the pepper.
    """
    settings = get_settings()
    pepper = settings.privacy.otp_pepper.get_secret_value().strip()
    if not pepper:
        # Fallback to JWT secret so existing deployments without OTP_PEPPER still work.
        pepper = settings.auth.jwt_secret or ""
    if not pepper:
        # Last-resort: use the salt itself (no server secret available).  Log a warning
        # so operators notice and configure OTP_PEPPER.
        logger.warning(
            "OTP_PEPPER is not set; OTP hashes are not protected by a server-side secret. "
            "Set OTP_PEPPER in your environment for production deployments."
        )
        pepper = salt
    msg = f"{salt}:{otp}".encode()
    return hmac.new(pepper.encode(), msg, hashlib.sha256).hexdigest()


def _parse_expires_at(expires_at_str: str) -> datetime:
    """Parse an ISO-8601 timestamp, normalising Z suffix."""
    s = expires_at_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.fromisoformat(expires_at_str)


def _log_otp_audit(
    conn: Any,
    action: str,
    claimant_identifier: str,
    *,
    verification_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Append an OTP audit entry to ``dsar_audit_log``."""
    details_json = json.dumps(details) if details else None
    conn.execute(
        text("""
            INSERT INTO dsar_audit_log (request_id, action, actor_id, details)
            VALUES (:request_id, :action, :actor_id, :details)
        """),
        {
            "request_id": verification_id,
            "action": action,
            "actor_id": claimant_identifier,
            "details": details_json,
        },
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def request_otp(
    claimant_identifier: str,
    channel: str,
    *,
    db_path: str | None = None,
) -> str:
    """Generate a DSAR OTP, deliver it via *channel*, and return ``verification_id``.

    The plaintext OTP is delivered to the claimant and **never stored**; only a
    salted HMAC-SHA256 hash is persisted.

    Args:
        claimant_identifier: Email address (``channel='email'``) or phone number
            (``channel='sms'``).
        channel: ``'email'`` or ``'sms'``.
        db_path: Optional DB path; uses the default when ``None``.

    Returns:
        A UUID string ``verification_id`` to pass to :func:`verify_otp`.

    Raises:
        ValueError: If *channel* is invalid.
        RateLimitExceeded: If the rate limit is exceeded.
    """
    if channel not in VALID_CHANNELS:
        raise ValueError(f"Invalid channel {channel!r}. Must be 'email' or 'sms'.")

    settings = get_settings()
    privacy = settings.privacy

    # Fail closed when self-service OTP is disabled in configuration.
    if not privacy.otp_enabled:
        raise PermissionError("DSAR self-service OTP flow is disabled by configuration.")

    path = db_path or get_db_path()
    now = datetime.now(timezone.utc)

    # --- Rate limiting (separate connection so audit entry commits) -----------
    window_start = (
        now - timedelta(minutes=privacy.otp_rate_limit_window_minutes)
    ).isoformat()
    rate_limited = False
    with get_connection(path) as conn:
        dialect = conn.dialect.name
        time_pred = _otp_rate_limit_time_predicate(dialect)
        count_row = conn.execute(
            text(
                f"SELECT COUNT(*) FROM dsar_verification_tokens "
                f"WHERE claimant_identifier = :identifier AND {time_pred}"
            ),
            {"identifier": claimant_identifier, "window_start": window_start},
        ).fetchone()
        request_count = count_row[0] if count_row else 0

        if request_count >= privacy.otp_rate_limit_max_requests:
            _log_otp_audit(
                conn,
                DSAR_AUDIT_OTP_RATE_LIMITED,
                claimant_identifier,
                details={
                    "channel": channel,
                    "window_minutes": privacy.otp_rate_limit_window_minutes,
                },
            )
            rate_limited = True

    # Raise *after* the connection closes so the audit entry is committed.
    if rate_limited:
        raise RateLimitExceeded(
            f"Rate limit exceeded: too many OTP requests for this identifier. "
            f"Try again after {privacy.otp_rate_limit_window_minutes} minutes."
        )

    # --- Token generation ------------------------------------------------
    otp = _generate_otp(privacy.otp_code_length)
    salt = _make_salt()
    token_hash = _hash_otp(otp, salt)
    verification_id = str(uuid.uuid4())
    expires_at = (now + timedelta(minutes=privacy.otp_ttl_minutes)).isoformat()

    with get_connection(path) as conn:
        conn.execute(
            text("""
                INSERT INTO dsar_verification_tokens
                    (verification_id, claimant_identifier, channel, token_hash, salt, expires_at)
                VALUES (:verification_id, :identifier, :channel, :token_hash, :salt, :expires_at)
            """),
            {
                "verification_id": verification_id,
                "identifier": claimant_identifier,
                "channel": channel,
                "token_hash": token_hash,
                "salt": salt,
                "expires_at": expires_at,
            },
        )

        _log_otp_audit(
            conn,
            DSAR_AUDIT_OTP_REQUESTED,
            claimant_identifier,
            verification_id=verification_id,
            details={"channel": channel, "expires_at": expires_at},
        )

    # Deliver OTP outside the DB transaction so a delivery failure does not
    # roll back the token row (the caller can retry / re-request).
    _deliver_otp(claimant_identifier, channel, otp, verification_id)

    return verification_id


def _deliver_otp(
    claimant_identifier: str,
    channel: str,
    otp: str,
    verification_id: str,
) -> None:
    """Send OTP to the claimant via the configured notification channel."""
    send_otp_notification(claimant_identifier, channel, otp, verification_id)


def verify_otp(
    verification_id: str,
    code: str,
    *,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Validate an OTP code and mark the token as used on success.

    Args:
        verification_id: The ``verification_id`` returned by :func:`request_otp`.
        code: Numeric OTP code submitted by the claimant.
        db_path: Optional DB path.

    Returns:
        Dict with:
        - ``verified`` (bool): ``True`` when the code is correct and the token
          is unexpired and unused.
        - ``message`` (str): Human-readable result description.

    Raises:
        ValueError: If *verification_id* is not found.
    """
    settings = get_settings()
    max_attempts = settings.privacy.otp_max_attempts
    path = db_path or get_db_path()
    now = datetime.now(timezone.utc)

    with get_connection(path) as conn:
        row = conn.execute(
            text("SELECT * FROM dsar_verification_tokens WHERE verification_id = :vid"),
            {"vid": verification_id},
        ).fetchone()

        if row is None:
            raise ValueError(f"Verification token not found: {verification_id}")

        token = row_to_dict(row)
        claimant_identifier = token["claimant_identifier"]

        # Already verified?
        if token.get("verified_at"):
            return {"verified": False, "message": "OTP has already been used."}

        # Expired?
        if now > _parse_expires_at(token["expires_at"]):
            _log_otp_audit(
                conn,
                DSAR_AUDIT_OTP_FAILED,
                claimant_identifier,
                verification_id=verification_id,
                details={"reason": "expired"},
            )
            return {
                "verified": False,
                "message": "OTP has expired. Please request a new one.",
            }

        # Too many failed attempts?
        attempts = int(token.get("attempts") or 0)
        if attempts >= max_attempts:
            return {
                "verified": False,
                "message": "Too many failed attempts. Please request a new OTP.",
            }

        # Verify HMAC
        expected_hash = _hash_otp(code, token["salt"])
        if not hmac.compare_digest(expected_hash, token["token_hash"]):
            conn.execute(
                text(
                    "UPDATE dsar_verification_tokens SET attempts = attempts + 1 "
                    "WHERE verification_id = :vid"
                ),
                {"vid": verification_id},
            )
            _log_otp_audit(
                conn,
                DSAR_AUDIT_OTP_FAILED,
                claimant_identifier,
                verification_id=verification_id,
                details={"reason": "invalid_code", "attempt": attempts + 1},
            )
            remaining = max(0, max_attempts - attempts - 1)
            return {
                "verified": False,
                "message": f"Invalid OTP code. {remaining} attempt(s) remaining.",
            }

        # Success – mark as verified
        conn.execute(
            text(
                "UPDATE dsar_verification_tokens SET verified_at = :now "
                "WHERE verification_id = :vid"
            ),
            {"now": now.isoformat(), "vid": verification_id},
        )
        _log_otp_audit(
            conn,
            DSAR_AUDIT_OTP_VERIFIED,
            claimant_identifier,
            verification_id=verification_id,
            details={"channel": token["channel"]},
        )

    return {"verified": True, "message": "OTP verified successfully."}


def get_verification_token(
    verification_id: str,
    *,
    db_path: str | None = None,
) -> dict[str, Any] | None:
    """Return token metadata (without hash / salt) or ``None`` if not found."""
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text(
                "SELECT verification_id, claimant_identifier, channel, "
                "expires_at, verified_at, attempts, created_at "
                "FROM dsar_verification_tokens WHERE verification_id = :vid"
            ),
            {"vid": verification_id},
        ).fetchone()
        return row_to_dict(row) if row is not None else None


def is_verified(
    verification_id: str,
    *,
    db_path: str | None = None,
) -> bool:
    """Return ``True`` when the token was verified and has not yet expired.

    Use this to gate DSAR fulfillment on a successful OTP check.
    """
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text(
                "SELECT verified_at, expires_at FROM dsar_verification_tokens "
                "WHERE verification_id = :vid"
            ),
            {"vid": verification_id},
        ).fetchone()
    if row is None:
        return False
    token = row_to_dict(row)
    if not token.get("verified_at"):
        return False
    return datetime.now(timezone.utc) <= _parse_expires_at(token["expires_at"])
