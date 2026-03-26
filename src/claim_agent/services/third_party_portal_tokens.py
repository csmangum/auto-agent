"""Create and verify third-party portal access tokens (per-claim, hashed)."""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, row_to_dict

logger = logging.getLogger(__name__)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class ThirdPartyTokenRecord:
    """Verified token row for a claim."""

    token_id: int
    claim_id: str
    party_id: int | None


def create_third_party_access_token(
    claim_id: str,
    *,
    party_id: int | None = None,
    db_path: str | None = None,
) -> str:
    """Insert a hashed token; return raw token once for the adjuster to send."""
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    settings = get_settings()
    expiry_days = settings.third_party_portal.token_expiry_days
    expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days)
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        conn.execute(
            text("""
                INSERT INTO third_party_access_tokens
                (claim_id, token_hash, party_id, expires_at)
                VALUES (:claim_id, :token_hash, :party_id, :expires_at)
            """),
            {
                "claim_id": claim_id,
                "token_hash": token_hash,
                "party_id": party_id,
                "expires_at": expires_at,
            },
        )
        conn.commit()
    logger.info("Created third-party portal access token for claim_id=%s", claim_id)
    return raw


def verify_third_party_token(
    claim_id: str,
    raw_token: str,
    *,
    db_path: str | None = None,
) -> ThirdPartyTokenRecord | None:
    """Return record if token is valid for this claim, not expired, and not inactive."""
    if not raw_token or not raw_token.strip():
        return None
    token_hash = _hash_token(raw_token.strip())
    now = datetime.now(timezone.utc)
    settings = get_settings()
    inactivity_cutoff = now - timedelta(
        days=settings.third_party_portal.inactivity_timeout_days
    )
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text("""
                SELECT id, claim_id, party_id, last_used_at FROM third_party_access_tokens
                WHERE claim_id = :claim_id AND token_hash = :token_hash
                AND expires_at > :now
            """),
            {"claim_id": claim_id, "token_hash": token_hash, "now": now},
        ).fetchone()
        if row is None:
            return None
        rec = row_to_dict(row)
        # Enforce inactivity timeout
        last_used = rec.get("last_used_at")
        if last_used is not None:
            try:
                last_used_dt = datetime.fromisoformat(
                    str(last_used).replace("Z", "+00:00")
                )
                if last_used_dt.tzinfo is None:
                    last_used_dt = last_used_dt.replace(tzinfo=timezone.utc)
                if last_used_dt < inactivity_cutoff:
                    logger.info(
                        "Rejecting inactive third-party token for claim_id=%s", claim_id
                    )
                    return None
            except (ValueError, TypeError):
                pass
        # Update last_used_at
        conn.execute(
            text("""
                UPDATE third_party_access_tokens
                SET last_used_at = :now
                WHERE id = :token_id
            """),
            {"now": now, "token_id": rec["id"]},
        )
        conn.commit()
    pid = rec.get("party_id")
    return ThirdPartyTokenRecord(
        token_id=int(rec["id"]),
        claim_id=str(rec["claim_id"]),
        party_id=int(pid) if pid is not None else None,
    )
