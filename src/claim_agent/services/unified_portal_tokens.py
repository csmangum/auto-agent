"""Create and verify unified external portal tokens (role-bearing, hashed).

Unified tokens live in ``external_portal_tokens`` and carry an explicit
``role`` so the backend can determine the caller's portal context from a
*single* credential without probing multiple legacy tables.

Security note (timing oracle)
------------------------------
The fallback detection in ``detect_role_from_headers`` probes legacy token
tables sequentially: repair_shop → claimant.  A sophisticated attacker who
can measure exact response latency could infer which table a stolen token
hash exists in.  The risk is low in practice (tokens are secrets) but
operators should be aware.  New integrations should issue unified tokens
(this module) which carry the role explicitly and eliminate the oracle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import text

from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, row_to_dict

logger = logging.getLogger(__name__)

PortalRole = Literal["claimant", "repair_shop", "tpa"]


def _hash_token(token: str) -> str:
    """SHA-256 hash of token for storage comparison."""
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class UnifiedTokenRecord:
    """Verified unified token row."""

    token_id: int
    role: PortalRole
    scopes: list[str]
    claim_id: str | None
    shop_id: str | None


def create_unified_portal_token(
    role: PortalRole,
    *,
    scopes: list[str] | None = None,
    claim_id: str | None = None,
    shop_id: str | None = None,
    db_path: str | None = None,
) -> str:
    """Insert a hashed unified token; return the raw token once for the issuer to deliver.

    Args:
        role: The portal role this token grants (``claimant``, ``repair_shop``, ``tpa``).
        scopes: Optional list of fine-grained permission strings.
        claim_id: Restrict to a specific claim (NULL means all assigned claims for the role).
        shop_id: Required when ``role == "repair_shop"`` to identify the shop.
        db_path: Override DB path (for testing).

    Returns:
        The raw token string.  Only returned once – not stored in plaintext.
    """
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    settings = get_settings()
    expiry_days = settings.portal.token_expiry_days
    expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days)
    scopes_json = json.dumps(scopes or [])
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        conn.execute(
            text("""
                INSERT INTO external_portal_tokens
                    (token_hash, role, scopes, claim_id, shop_id, expires_at)
                VALUES
                    (:token_hash, :role, :scopes, :claim_id, :shop_id, :expires_at)
            """),
            {
                "token_hash": token_hash,
                "role": role,
                "scopes": scopes_json,
                "claim_id": claim_id,
                "shop_id": shop_id,
                "expires_at": expires_at,
            },
        )
        conn.commit()
    logger.info("Created unified portal token role=%s claim_id=%s", role, claim_id)
    return raw


def verify_unified_portal_token(
    raw_token: str,
    *,
    db_path: str | None = None,
) -> UnifiedTokenRecord | None:
    """Return record if token is valid and not expired/revoked; None otherwise."""
    if not raw_token or not raw_token.strip():
        return None
    token_hash = _hash_token(raw_token.strip())
    now = datetime.now(timezone.utc)
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text("""
                SELECT id, role, scopes, claim_id, shop_id
                FROM external_portal_tokens
                WHERE token_hash = :token_hash
                  AND expires_at > :now
                  AND revoked_at IS NULL
            """),
            {"token_hash": token_hash, "now": now},
        ).fetchone()
    if row is None:
        return None
    rec = row_to_dict(row)
    try:
        scopes: list[str] = json.loads(rec.get("scopes") or "[]")
    except (ValueError, TypeError):
        scopes = []
    return UnifiedTokenRecord(
        token_id=int(rec["id"]),
        role=str(rec["role"]),  # type: ignore[arg-type]
        scopes=scopes,
        claim_id=rec.get("claim_id"),
        shop_id=rec.get("shop_id"),
    )


def revoke_unified_portal_token(
    raw_token: str,
    *,
    db_path: str | None = None,
) -> bool:
    """Mark a token as revoked. Returns True if a token was found and revoked."""
    if not raw_token or not raw_token.strip():
        return False
    token_hash = _hash_token(raw_token.strip())
    now = datetime.now(timezone.utc)
    path = db_path or get_db_path()
    with get_connection(path) as conn:
        result = conn.execute(
            text("""
                UPDATE external_portal_tokens
                SET revoked_at = :now
                WHERE token_hash = :token_hash AND revoked_at IS NULL
            """),
            {"token_hash": token_hash, "now": now},
        )
        conn.commit()
        return (result.rowcount or 0) > 0
