"""Idempotency key support for claim-creation endpoints.

When clients send an optional Idempotency-Key header, duplicate requests
with the same key return the cached response without creating a new claim.
"""

import json
import logging
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, _is_postgres

logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
_DEFAULT_TTL_SECONDS = 86400  # 24 hours


def _get_ttl_seconds() -> int:
    """Return configured TTL for idempotency keys."""
    try:
        return get_settings().idempotency_ttl_seconds
    except Exception:
        return _DEFAULT_TTL_SECONDS


def check_idempotency(key: str, db_path: str | None = None) -> tuple[int, dict] | None:
    """Return (status, body) if key exists and not expired, else None."""
    if not key or not key.strip():
        return None
    key = key.strip()
    now = datetime.now(timezone.utc)
    path = db_path if db_path is not None else get_db_path()
    with get_connection(path) as conn:
        row = conn.execute(
            text("""
                SELECT response_status, response_body, expires_at
                FROM idempotency_keys
                WHERE idempotency_key = :key
            """),
            {"key": key},
        ).fetchone()
        if row is None:
            return None
        status = int(row[0])
        body_str = row[1]
        expires_at_str = row[2]
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
        if expires_at < now:
            conn.execute(
                text("DELETE FROM idempotency_keys WHERE idempotency_key = :key"),
                {"key": key},
            )
            return None
        try:
            body = json.loads(body_str) if isinstance(body_str, str) else body_str
        except json.JSONDecodeError:
            return None
        return (status, body)


def store_idempotency(
    key: str,
    status: int,
    body: dict,
    ttl_seconds: int | None = None,
    db_path: str | None = None,
) -> None:
    """Store idempotency key with response and TTL."""
    if not key or not key.strip():
        return
    key = key.strip()
    ttl = ttl_seconds if ttl_seconds is not None else _get_ttl_seconds()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)
    body_str = json.dumps(body, default=str)
    path = db_path if db_path is not None else get_db_path()
    params = {
        "key": key,
        "status": status,
        "body": body_str,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    with get_connection(path) as conn:
        if _is_postgres():
            conn.execute(
                text("""
                    INSERT INTO idempotency_keys
                    (idempotency_key, response_status, response_body, created_at, expires_at)
                    VALUES (:key, :status, :body, :created_at, :expires_at)
                    ON CONFLICT (idempotency_key) DO UPDATE SET
                    response_status = EXCLUDED.response_status,
                    response_body = EXCLUDED.response_body,
                    created_at = EXCLUDED.created_at,
                    expires_at = EXCLUDED.expires_at
                """),
                params,
            )
        else:
            conn.execute(
                text("""
                    INSERT OR REPLACE INTO idempotency_keys
                    (idempotency_key, response_status, response_body, created_at, expires_at)
                    VALUES (:key, :status, :body, :created_at, :expires_at)
                """),
                params,
            )


def get_idempotency_key_and_cached(
    request: Request, db_path: str | None = None
) -> tuple[str | None, JSONResponse | None]:
    """Return (key, cached_response). If cached_response is not None, return it immediately."""
    key = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    if not key or not key.strip():
        return None, None
    key = key.strip()
    cached = check_idempotency(key, db_path)
    if cached:
        status, body = cached
        return key, JSONResponse(status_code=status, content=body)
    return key, None


def store_response_if_idempotent(
    key: str | None, status: int, body: dict[str, Any], db_path: str | None = None
) -> None:
    """Store idempotency key with response when key was provided."""
    if key:
        store_idempotency(key, status, body, db_path=db_path)


def cleanup_expired(db_path: str | None = None) -> int:
    """Delete expired idempotency keys. Returns count deleted."""
    now = datetime.now(timezone.utc).isoformat()
    path = db_path if db_path is not None else get_db_path()
    with get_connection(path) as conn:
        result = conn.execute(
            text("DELETE FROM idempotency_keys WHERE expires_at < :now"),
            {"now": now},
        )
        return result.rowcount or 0
