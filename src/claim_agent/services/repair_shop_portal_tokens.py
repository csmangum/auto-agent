"""Create and verify repair shop portal access tokens (per-claim, hashed)."""

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
    portal_token_last_used_rejects,
)

logger = logging.getLogger(__name__)


@dataclass
class RepairShopTokenRecord:
    """Verified token row for a claim."""

    token_id: int
    claim_id: str
    shop_id: str | None


def create_repair_shop_access_token(
    claim_id: str,
    *,
    shop_id: str | None = None,
    db_path: str | None = None,
) -> str:
    """Insert a hashed token; return raw token once for the adjuster to send to the shop."""
    raw = secrets.token_urlsafe(32)
    token_hash = hash_portal_token(raw)
    settings = get_settings()
    expiry_days = settings.repair_shop_portal.token_expiry_days
    expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days)
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        conn.execute(
            text("""
                INSERT INTO repair_shop_access_tokens
                (claim_id, token_hash, shop_id, expires_at)
                VALUES (:claim_id, :token_hash, :shop_id, :expires_at)
            """),
            {
                "claim_id": claim_id,
                "token_hash": token_hash,
                "shop_id": (shop_id or None),
                "expires_at": expires_at,
            },
        )
        conn.commit()
    logger.info("Created repair shop access token for claim_id=%s", claim_id)
    return raw


def verify_repair_shop_token(
    claim_id: str,
    raw_token: str,
    *,
    db_path: str | None = None,
) -> RepairShopTokenRecord | None:
    """Return record if token is valid for this claim, not expired, and not inactive."""
    if not raw_token or not raw_token.strip():
        return None
    token_hash = hash_portal_token(raw_token.strip())
    now = datetime.now(timezone.utc)
    settings = get_settings()
    inactivity_cutoff = now - timedelta(days=settings.repair_shop_portal.inactivity_timeout_days)
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text("""
                SELECT id, claim_id, shop_id, last_used_at FROM repair_shop_access_tokens
                WHERE claim_id = :claim_id AND token_hash = :token_hash
                AND expires_at > :now
            """),
            {"claim_id": claim_id, "token_hash": token_hash, "now": now},
        ).fetchone()
        if row is None:
            return None
        rec = row_to_dict(row)
        if portal_token_last_used_rejects(
            rec.get("last_used_at"),
            inactivity_cutoff,
            logger=logger,
            inactive_log="Rejecting inactive repair shop token for claim_id=%s",
            inactive_args=(claim_id,),
            token_id=rec.get("id"),
        ):
            return None
        # Update last_used_at
        conn.execute(
            text("""
                UPDATE repair_shop_access_tokens
                SET last_used_at = :now
                WHERE id = :token_id
            """),
            {"now": now, "token_id": rec["id"]},
        )
        conn.commit()
    return RepairShopTokenRecord(
        token_id=int(rec["id"]),
        claim_id=str(rec["claim_id"]),
        shop_id=rec.get("shop_id"),
    )
