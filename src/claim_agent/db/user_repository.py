"""User and refresh-token persistence for Auth Phase 2."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from claim_agent.api.auth import KNOWN_ROLES
from claim_agent.db.database import get_connection, is_postgres_backend, row_to_dict

MIN_PASSWORD_LENGTH = 8


def hash_password(plain: str) -> str:
    """Return bcrypt hash string for storage."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def hash_refresh_token(raw_token: str) -> str:
    """SHA-256 hex digest for opaque refresh token storage."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dt_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class UserRepository:
    """CRUD for users and refresh token lifecycle."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path

    def create_user(
        self,
        email: str,
        password: str,
        role: str,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        if role not in KNOWN_ROLES:
            raise ValueError(f"Invalid role: {role}")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        uid = user_id or str(uuid.uuid4())
        em = email.strip().lower()
        ph = hash_password(password)
        now = _dt_iso(_utcnow())
        with get_connection(self._db_path) as conn:
            try:
                conn.execute(
                    text(
                        """
                        INSERT INTO users (id, email, password_hash, role, is_active, created_at, updated_at)
                        VALUES (:id, :email, :password_hash, :role, 1, :created_at, :updated_at)
                        """
                    ),
                    {
                        "id": uid,
                        "email": em,
                        "password_hash": ph,
                        "role": role,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            except IntegrityError as e:
                raise ValueError("Email already registered") from e
        return self.get_user_by_id(uid)  # type: ignore[return-value]

    def get_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id, email, role, is_active, created_at, updated_at FROM users WHERE id = :id"),
                {"id": user_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_user_by_email(self, email: str) -> dict[str, Any] | None:
        em = email.strip().lower()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT id, email, password_hash, role, is_active, created_at, updated_at "
                    "FROM users WHERE email = :email"
                ),
                {"email": em},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_user_with_password_by_email(self, email: str) -> dict[str, Any] | None:
        em = email.strip().lower()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT * FROM users WHERE email = :email"),
                {"email": em},
            ).fetchone()
        return row_to_dict(row) if row else None

    def list_users(self, *, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text(
                    "SELECT id, email, role, is_active, created_at, updated_at FROM users "
                    "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"limit": limit, "offset": offset},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_users(self) -> int:
        with get_connection(self._db_path) as conn:
            row = conn.execute(text("SELECT COUNT(*) AS c FROM users")).fetchone()
        return int(row[0]) if row else 0

    def update_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        role: str | None = None,
        is_active: bool | None = None,
        password: str | None = None,
    ) -> dict[str, Any] | None:
        fields: list[str] = []
        params: dict[str, Any] = {"id": user_id}
        if email is not None:
            fields.append("email = :email")
            params["email"] = email.strip().lower()
        if role is not None:
            if role not in KNOWN_ROLES:
                raise ValueError(f"Invalid role: {role}")
            fields.append("role = :role")
            params["role"] = role
        if is_active is not None:
            fields.append("is_active = :is_active")
            params["is_active"] = 1 if is_active else 0
        if password is not None:
            if len(password) < MIN_PASSWORD_LENGTH:
                raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
            fields.append("password_hash = :password_hash")
            params["password_hash"] = hash_password(password)
        if not fields:
            return self.get_user_by_id(user_id)
        now = _dt_iso(_utcnow())
        fields.append("updated_at = :updated_at")
        params["updated_at"] = now
        with get_connection(self._db_path) as conn:
            conn.execute(
                text(f"UPDATE users SET {', '.join(fields)} WHERE id = :id"),
                params,
            )
        return self.get_user_by_id(user_id)

    def delete_user(self, user_id: str) -> bool:
        with get_connection(self._db_path) as conn:
            r = conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            rc = getattr(r, "rowcount", 0) or 0
            return int(rc) > 0

    def verify_user_password(self, email: str, password: str) -> dict[str, Any] | None:
        row = self.get_user_with_password_by_email(email)
        if row is None or not row.get("is_active"):
            return None
        ph = row.get("password_hash") or ""
        if not verify_password(password, str(ph)):
            return None
        row.pop("password_hash", None)
        return row

    def issue_refresh_token(self, user_id: str, ttl_seconds: int) -> tuple[str, str]:
        """Return (raw_token, token_row_id). Stores hash only."""
        raw = secrets.token_urlsafe(48)
        tid = str(uuid.uuid4())
        th = hash_refresh_token(raw)
        now = _utcnow()
        exp = now + timedelta(seconds=ttl_seconds)
        with get_connection(self._db_path) as conn:
            if is_postgres_backend():
                conn.execute(
                    text(
                        """
                        INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)
                        VALUES (:id, :user_id, :token_hash, :expires_at, :created_at)
                        """
                    ),
                    {
                        "id": tid,
                        "user_id": user_id,
                        "token_hash": th,
                        "expires_at": exp,
                        "created_at": now,
                    },
                )
            else:
                conn.execute(
                    text(
                        """
                        INSERT INTO refresh_tokens (id, user_id, token_hash, expires_at, created_at)
                        VALUES (:id, :user_id, :token_hash, :expires_at, :created_at)
                        """
                    ),
                    {
                        "id": tid,
                        "user_id": user_id,
                        "token_hash": th,
                        "expires_at": _dt_iso(exp),
                        "created_at": _dt_iso(now),
                    },
                )
        return raw, tid

    def get_refresh_token_row_by_hash(self, token_hash: str) -> dict[str, Any] | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT id, user_id, token_hash, expires_at, revoked_at, replaced_by, created_at "
                    "FROM refresh_tokens WHERE token_hash = :h"
                ),
                {"h": token_hash},
            ).fetchone()
        return row_to_dict(row) if row else None

    def revoke_refresh_token(self, token_id: str, *, replaced_by: str | None = None) -> None:
        now = _utcnow()
        with get_connection(self._db_path) as conn:
            if is_postgres_backend():
                conn.execute(
                    text(
                        "UPDATE refresh_tokens SET revoked_at = :rv, replaced_by = :rb WHERE id = :id"
                    ),
                    {"id": token_id, "rv": now, "rb": replaced_by},
                )
            else:
                conn.execute(
                    text(
                        "UPDATE refresh_tokens SET revoked_at = :rv, replaced_by = :rb WHERE id = :id"
                    ),
                    {"id": token_id, "rv": _dt_iso(now), "rb": replaced_by},
                )

    def rotate_refresh_token(
        self,
        old_token_id: str,
        user_id: str,
        ttl_seconds: int,
    ) -> tuple[str, str]:
        """Revoke old row and issue new refresh token. Returns (raw_token, new_row_id)."""
        raw, new_id = self.issue_refresh_token(user_id, ttl_seconds)
        self.revoke_refresh_token(old_token_id, replaced_by=new_id)
        return raw, new_id

    def is_refresh_token_valid(self, row: dict[str, Any]) -> bool:
        if row.get("revoked_at"):
            return False
        exp = row.get("expires_at")
        if exp is None:
            return False
        if isinstance(exp, datetime):
            exp_dt = exp if exp.tzinfo else exp.replace(tzinfo=timezone.utc)
            return _utcnow() < exp_dt
        try:
            exp_dt = datetime.fromisoformat(str(exp).replace("Z", "+00:00"))
            if exp_dt.tzinfo is None:
                exp_dt = exp_dt.replace(tzinfo=timezone.utc)
            return _utcnow() < exp_dt
        except (ValueError, TypeError):
            return False
