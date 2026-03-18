"""Idempotency key support for claim-creation endpoints.

When clients send an optional Idempotency-Key header, duplicate requests
with the same key return the cached response without creating a new claim.

Uses claim-before-process pattern: first request inserts with status=in_progress,
processes, then updates to completed. Duplicate requests see in_progress (409) or
completed (cached). Only 200 responses are cached; 4xx/5xx are not.
"""

import hashlib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, _is_postgres

logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_HEADER = "Idempotency-Key"
_DEFAULT_TTL_SECONDS = 86400  # 24 hours
_MAX_KEY_LENGTH = 256
_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")

# Result of try_claim: "owned" = we process, "cached" = return cached, "in_progress" = 409
_IdempotencyClaimResult = str  # Literal["owned", "cached", "in_progress"]


def _get_ttl_seconds() -> int:
    """Return configured TTL for idempotency keys."""
    try:
        return get_settings().idempotency_ttl_seconds
    except (ImportError, AttributeError, ValueError):
        return _DEFAULT_TTL_SECONDS


def _validate_key(key: str) -> str | None:
    """Return normalized key if valid, else None. Rejects empty, too long, or invalid chars."""
    if not key or not key.strip():
        return None
    key = key.strip()
    if len(key) > _MAX_KEY_LENGTH:
        return None
    if not _KEY_PATTERN.match(key):
        return None
    return key


def _try_claim_key(key: str, db_path: str | None) -> tuple[_IdempotencyClaimResult, int | None, dict | None]:
    """Try to claim idempotency key. Returns (result, status, body).

    - "owned": caller should process; (None, None) for status/body
    - "cached": return cached response; (status, body)
    - "in_progress": another request is processing; (None, None)
    """
    path = db_path if db_path is not None else get_db_path()
    ttl = _get_ttl_seconds()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)
    params = {
        "key": key,
        "status": "in_progress",
        "response_status": 0,
        "body": "{}",
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    with get_connection(path) as conn:
        try:
            conn.execute(
                text("""
                    INSERT INTO idempotency_keys
                    (idempotency_key, status, response_status, response_body, created_at, expires_at)
                    VALUES (:key, :status, :response_status, :body, :created_at, :expires_at)
                """),
                params,
            )
            return "owned", None, None
        except IntegrityError:
            conn.rollback()

        row = conn.execute(
            text("""
                SELECT status, response_status, response_body, expires_at
                FROM idempotency_keys
                WHERE idempotency_key = :key
            """),
            {"key": key},
        ).fetchone()
        if row is None:
            return "owned", None, None  # Race: deleted between insert and select
        db_status, resp_status, body_str, expires_at_value = row
        try:
            if isinstance(expires_at_value, datetime):
                expires_at = expires_at_value
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            elif isinstance(expires_at_value, str):
                normalized = expires_at_value.replace("Z", "+00:00")
                expires_at = datetime.fromisoformat(normalized)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            else:
                raise TypeError(f"Unsupported expires_at type: {type(expires_at_value)!r}")
        except (ValueError, TypeError):
            conn.execute(
                text("DELETE FROM idempotency_keys WHERE idempotency_key = :key"),
                {"key": key},
            )
            return "owned", None, None
        if expires_at < now:
            conn.execute(
                text("DELETE FROM idempotency_keys WHERE idempotency_key = :key"),
                {"key": key},
            )
            return "owned", None, None

        if db_status == "in_progress":
            return "in_progress", None, None
        if db_status == "completed":
            try:
                body = json.loads(body_str) if isinstance(body_str, str) else body_str
            except json.JSONDecodeError:
                return "owned", None, None
            return "cached", int(resp_status), body
        return "owned", None, None


def _complete_claim(key: str, status: int, body: dict, db_path: str | None) -> None:
    """Update idempotency key to completed with response."""
    path = db_path if db_path is not None else get_db_path()
    ttl = _get_ttl_seconds()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)
    body_str = json.dumps(body, default=str)
    params = {
        "key": key,
        "status": "completed",
        "response_status": status,
        "body": body_str,
        "expires_at": expires_at.isoformat(),
    }
    with get_connection(path) as conn:
        conn.execute(
            text("""
                UPDATE idempotency_keys
                SET status = :status, response_status = :response_status,
                    response_body = :body, expires_at = :expires_at
                WHERE idempotency_key = :key
            """),
            params,
        )


def _build_scoped_idempotency_key(request: Request, key: str) -> str:
    """Build a scoped idempotency key including identity and route.

    Prevents different clients or endpoints from sharing cached responses
    when they reuse the same raw Idempotency-Key header.
    """
    method = request.method.upper()
    path = request.url.path
    identity_parts: list[str] = []
    auth_header = request.headers.get("Authorization")
    if auth_header:
        identity_parts.append(f"auth_sha256:{hashlib.sha256(auth_header.encode()).hexdigest()}")
    if request.client and request.client.host:
        identity_parts.append(f"client:{request.client.host}")
    identity = "|".join(identity_parts) if identity_parts else "anonymous"
    return f"{identity}:{method}:{path}:{key}"


def _release_claim(key: str, db_path: str | None) -> None:
    """Delete in-progress idempotency key so client can retry."""
    path = db_path if db_path is not None else get_db_path()
    with get_connection(path) as conn:
        conn.execute(
            text("DELETE FROM idempotency_keys WHERE idempotency_key = :key AND status = 'in_progress'"),
            {"key": key},
        )


def get_idempotency_key_and_cached(
    request: Request, db_path: str | None = None
) -> tuple[str | None, JSONResponse | None]:
    """Return (key, response). If response is not None, return it immediately.

    Response can be: cached 200, 400 (invalid key), or 409 (request in progress).
    Only 200 responses are cached; 4xx/5xx are not.
    """
    raw = request.headers.get(IDEMPOTENCY_KEY_HEADER)
    key = _validate_key(raw) if raw else None
    if key is None:
        if raw is not None and raw.strip():
            return None, JSONResponse(
                status_code=400,
                content={
                    "detail": (
                        f"Idempotency-Key must be 1-{_MAX_KEY_LENGTH} chars, "
                        "alphanumeric, hyphen, or underscore only."
                    )
                },
            )
        return None, None

    scoped_key = _build_scoped_idempotency_key(request, key)
    result, status, body = _try_claim_key(scoped_key, db_path)
    if result == "owned":
        return scoped_key, None
    if result == "cached" and status is not None and body is not None:
        return scoped_key, JSONResponse(status_code=status, content=body)
    if result == "in_progress":
        return scoped_key, JSONResponse(
            status_code=409,
            content={"detail": "A request with this idempotency key is already in progress. Retry later."},
            headers={"Retry-After": "5"},
        )
    return scoped_key, None


def store_response_if_idempotent(
    key: str | None, status: int, body: dict[str, Any], db_path: str | None = None
) -> None:
    """Store idempotency key with response when key was provided. Only caches 200."""
    if not key:
        return
    if status == 200:
        _complete_claim(key, status, body, db_path)
    else:
        _release_claim(key, db_path)


def release_idempotency_on_error(key: str | None, db_path: str | None = None) -> None:
    """Release in-progress idempotency key so client can retry with same key."""
    if key:
        _release_claim(key, db_path)


def cleanup_expired(db_path: str | None = None) -> int:
    """Delete expired idempotency keys. Returns count deleted."""
    path = db_path if db_path is not None else get_db_path()
    now = datetime.now(timezone.utc)
    now_str = now.isoformat()
    with get_connection(path) as conn:
        result = conn.execute(
            text("DELETE FROM idempotency_keys WHERE expires_at < :now"),
            {"now": now_str},
        )
        return result.rowcount or 0


# Legacy helpers for tests (preserve check_idempotency / store_idempotency for backward compat)
def check_idempotency(key: str, db_path: str | None = None) -> tuple[int, dict] | None:
    """Return (status, body) if key exists, completed, and not expired, else None."""
    if not key or not key.strip():
        return None
    key = key.strip()
    path = db_path if db_path is not None else get_db_path()
    now = datetime.now(timezone.utc)
    with get_connection(path) as conn:
        row = conn.execute(
            text("""
                SELECT status, response_status, response_body, expires_at
                FROM idempotency_keys
                WHERE idempotency_key = :key
            """),
            {"key": key},
        ).fetchone()
        if row is None:
            return None
        db_status, resp_status, body_str, expires_at_value = row
        if db_status != "completed":
            return None
        try:
            if isinstance(expires_at_value, datetime):
                expires_at = expires_at_value
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            elif isinstance(expires_at_value, str):
                normalized = expires_at_value.replace("Z", "+00:00")
                expires_at = datetime.fromisoformat(normalized)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            else:
                return None
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
        return (int(resp_status), body)


def store_idempotency(
    key: str,
    status: int,
    body: dict,
    ttl_seconds: int | None = None,
    db_path: str | None = None,
) -> None:
    """Store idempotency key with response and TTL. For tests; prefer store_response_if_idempotent."""
    if not key or not key.strip():
        return
    key = key.strip()
    path = db_path if db_path is not None else get_db_path()
    ttl = ttl_seconds if ttl_seconds is not None else _get_ttl_seconds()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=ttl)
    body_str = json.dumps(body, default=str)
    params = {
        "key": key,
        "status": "completed",
        "response_status": status,
        "body": body_str,
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    with get_connection(path) as conn:
        if _is_postgres():
            conn.execute(
                text("""
                    INSERT INTO idempotency_keys
                    (idempotency_key, status, response_status, response_body, created_at, expires_at)
                    VALUES (:key, :status, :response_status, :body, :created_at, :expires_at)
                    ON CONFLICT (idempotency_key) DO UPDATE SET
                    status = EXCLUDED.status, response_status = EXCLUDED.response_status,
                    response_body = EXCLUDED.response_body, expires_at = EXCLUDED.expires_at
                """),
                params,
            )
        else:
            conn.execute(
                text("""
                    INSERT OR REPLACE INTO idempotency_keys
                    (idempotency_key, status, response_status, response_body, created_at, expires_at)
                    VALUES (:key, :status, :response_status, :body, :created_at, :expires_at)
                """),
                params,
            )
