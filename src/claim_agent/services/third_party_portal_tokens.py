"""Create and verify third-party portal access tokens (per-claim, hashed)."""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.services.portal_token_utils import (
    hash_portal_token,
    verify_inactivity_then_touch_last_used,
)

logger = logging.getLogger(__name__)


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
    token_hash = hash_portal_token(raw)
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
    token_hash = hash_portal_token(raw_token.strip())
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
        if not verify_inactivity_then_touch_last_used(
            conn,
            row=rec,
            table="third_party_access_tokens",
            now=now,
            inactivity_cutoff=inactivity_cutoff,
            logger=logger,
            inactive_log="Rejecting inactive third-party token for claim_id=%s",
            inactive_args=(claim_id,),
        ):
            return None
        conn.commit()
    pid = rec.get("party_id")
    return ThirdPartyTokenRecord(
        token_id=int(rec["id"]),
        claim_id=str(rec["claim_id"]),
        party_id=int(pid) if pid is not None else None,
    )
