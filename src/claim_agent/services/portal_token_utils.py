"""Shared helpers for portal magic-link token hashing and last-used inactivity checks."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

_PORTAL_TOKEN_LAST_USED_SQL: dict[str, str] = {
    "claim_access_tokens": (
        "UPDATE claim_access_tokens SET last_used_at = :now WHERE id = :token_id"
    ),
    "repair_shop_access_tokens": (
        "UPDATE repair_shop_access_tokens SET last_used_at = :now WHERE id = :token_id"
    ),
    "third_party_access_tokens": (
        "UPDATE third_party_access_tokens SET last_used_at = :now WHERE id = :token_id"
    ),
    "external_portal_tokens": (
        "UPDATE external_portal_tokens SET last_used_at = :now WHERE id = :token_id"
    ),
}


def hash_portal_token(token: str) -> str:
    """SHA-256 hash of token for storage comparison."""
    return hashlib.sha256(token.encode()).hexdigest()


def portal_token_last_used_rejects(
    last_used: object | None,
    inactivity_cutoff: datetime,
    *,
    logger: logging.Logger,
    inactive_log: str | None,
    inactive_args: tuple[Any, ...] = (),
    token_id: object | None = None,
) -> bool:
    """Return True if verification must reject due to inactivity or bad ``last_used_at``.

    - If ``last_used`` is None, returns False (no inactivity evidence yet).
    - If parsed UTC datetime is strictly before ``inactivity_cutoff``, returns True.
    - If parsing fails, logs a warning and returns True (fail closed).
    """
    if last_used is None:
        return False
    try:
        last_used_dt = datetime.fromisoformat(str(last_used).replace("Z", "+00:00"))
        if last_used_dt.tzinfo is None:
            last_used_dt = last_used_dt.replace(tzinfo=timezone.utc)
        if last_used_dt < inactivity_cutoff:
            if inactive_log:
                logger.info(inactive_log, *inactive_args)
            return True
        return False
    except (ValueError, TypeError):
        logger.warning(
            "Unparseable last_used_at for portal token id=%s; rejecting",
            token_id,
        )
        return True


def refresh_portal_token_last_used(conn: Any, table: str, token_id: int, now: Any) -> None:
    """Set ``last_used_at`` for a portal token row (table name allowlisted)."""
    sql = _PORTAL_TOKEN_LAST_USED_SQL.get(table)
    if not sql:
        raise ValueError(f"Unknown portal token table: {table!r}")
    conn.execute(text(sql), {"now": now, "token_id": token_id})


def verify_inactivity_then_touch_last_used(
    conn: Any,
    *,
    row: dict[str, Any],
    table: str,
    now: Any,
    inactivity_cutoff: datetime,
    logger: logging.Logger,
    inactive_log: str,
    inactive_args: tuple[Any, ...] = (),
) -> bool:
    """If ``last_used_at`` is stale or invalid, return False; else update DB and return True."""
    if portal_token_last_used_rejects(
        row.get("last_used_at"),
        inactivity_cutoff,
        logger=logger,
        inactive_log=inactive_log,
        inactive_args=inactive_args,
        token_id=row.get("id"),
    ):
        return False
    refresh_portal_token_last_used(conn, table, int(row["id"]), now)
    return True
