"""Create and verify unified external portal tokens (role-bearing, hashed).

Unified tokens live in ``external_portal_tokens`` and carry an explicit
``role`` so the backend can determine the caller's portal context from a
*single* credential without probing multiple legacy tables.

Some **legacy** resolution paths elsewhere in the API (for example, guessing
role from separate headers and looking up ``repair_shop_access_tokens`` vs
``claim_access_tokens`` in sequence) could in theory allow a timing oracle
across tables. The practical risk is very low (tokens are secrets). New
integrations should prefer unified tokens, which carry ``role`` explicitly and
avoid that class of ambiguity.
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
from claim_agent.db.database import get_connection, get_db_path, is_postgres_backend, row_to_dict

logger = logging.getLogger(__name__)

PortalRole = Literal["claimant", "repair_shop", "tpa"]

KNOWN_PORTAL_ROLES: frozenset[str] = frozenset({"claimant", "repair_shop", "tpa"})

VALID_PORTAL_SCOPES: frozenset[str] = frozenset(
    {
        "read_claim",
        "upload_doc",
        "update_repair_status",
        "view_estimate",
        "submit_supplement",
        "respond_followup",
    }
)


def _hash_token(token: str) -> str:
    """SHA-256 hash of token for storage comparison."""
    return hashlib.sha256(token.encode()).hexdigest()


def _ts(dt: datetime) -> str:
    """Format a UTC datetime as a sortable string for SQLite TEXT columns.

    Uses the same format as SQLite's ``datetime('now')`` so that string
    comparisons (``>``, ``<``) in WHERE clauses work correctly.  Also
    valid for PostgreSQL TIMESTAMPTZ (interpreted as UTC).
    """
    return dt.strftime("%Y-%m-%d %H:%M:%S")


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
        claim_id: Required for all roles; session code resolves access from this claim.
        shop_id: Required when ``role == "repair_shop"`` to identify the shop.
        db_path: Override DB path (for testing).

    Returns:
        The raw token string.  Only returned once – not stored in plaintext.

    Raises:
        ValueError: If any scope string is not in ``VALID_PORTAL_SCOPES``, or
            required fields for the role are missing.
    """
    if scopes:
        invalid = set(scopes) - VALID_PORTAL_SCOPES
        if invalid:
            raise ValueError(f"Invalid portal scopes: {sorted(invalid)}")
    if not claim_id or not str(claim_id).strip():
        raise ValueError("claim_id is required for unified portal tokens")
    if role == "repair_shop" and not (shop_id and str(shop_id).strip()):
        raise ValueError("shop_id is required when role is repair_shop")
    raw = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    settings = get_settings()
    if role == "repair_shop":
        expiry_days = settings.repair_shop_portal.token_expiry_days
    elif role == "tpa":
        expiry_days = settings.third_party_portal.token_expiry_days
    else:
        expiry_days = settings.portal.token_expiry_days
    expires_at_dt = datetime.now(timezone.utc) + timedelta(days=expiry_days)
    # Bind timezone-aware datetimes for PostgreSQL; SQLite TEXT columns use UTC strings.
    expires_at: datetime | str = (
        expires_at_dt if is_postgres_backend() else _ts(expires_at_dt)
    )
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
    now_param: datetime | str = now if is_postgres_backend() else _ts(now)
    with get_connection(path) as conn:
        row = conn.execute(
            text("""
                SELECT id, role, scopes, claim_id, shop_id
                FROM external_portal_tokens
                WHERE token_hash = :token_hash
                  AND expires_at > :now
                  AND revoked_at IS NULL
            """),
            {"token_hash": token_hash, "now": now_param},
        ).fetchone()
    if row is None:
        return None
    rec = row_to_dict(row)
    role_str = str(rec.get("role") or "").strip()
    if role_str not in KNOWN_PORTAL_ROLES:
        logger.warning(
            "Rejecting unified portal token with unknown role from database: %r",
            role_str,
        )
        return None
    try:
        scopes: list[str] = json.loads(rec.get("scopes") or "[]")
    except (ValueError, TypeError):
        scopes = []
    return UnifiedTokenRecord(
        token_id=int(rec["id"]),
        role=role_str,  # type: ignore[arg-type]
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
    now_param: datetime | str = now if is_postgres_backend() else _ts(now)
    with get_connection(path) as conn:
        result = conn.execute(
            text("""
                UPDATE external_portal_tokens
                SET revoked_at = :now
                WHERE token_hash = :token_hash AND revoked_at IS NULL
            """),
            {"token_hash": token_hash, "now": now_param},
        )
        conn.commit()
        return (result.rowcount or 0) > 0
