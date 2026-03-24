"""Repair shop user accounts and claim assignment persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import bcrypt
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from claim_agent.db.database import get_connection, row_to_dict


MIN_PASSWORD_LENGTH = 8


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _verify_password(plain: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class RepairShopUserRepository:
    """CRUD for repair shop user accounts and claim assignments."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path

    # ------------------------------------------------------------------
    # Shop user management
    # ------------------------------------------------------------------

    def create_shop_user(
        self,
        shop_id: str,
        email: str,
        password: str,
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a repair shop user account. Raises ValueError on duplicate email."""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")
        uid = user_id or str(uuid.uuid4())
        em = email.strip().lower()
        ph = _hash_password(password)
        now = _utcnow_iso()
        with get_connection(self._db_path) as conn:
            try:
                conn.execute(
                    text(
                        """
                        INSERT INTO repair_shop_users
                            (id, shop_id, email, password_hash, is_active, created_at, updated_at)
                        VALUES
                            (:id, :shop_id, :email, :password_hash, 1, :created_at, :updated_at)
                        """
                    ),
                    {
                        "id": uid,
                        "shop_id": shop_id.strip(),
                        "email": em,
                        "password_hash": ph,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            except IntegrityError as e:
                raise ValueError("Email already registered") from e
        return self.get_shop_user_by_id(uid)  # type: ignore[return-value]

    def get_shop_user_by_id(self, user_id: str) -> dict[str, Any] | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT id, shop_id, email, is_active, created_at, updated_at "
                    "FROM repair_shop_users WHERE id = :id"
                ),
                {"id": user_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_shop_user_by_email(self, email: str) -> dict[str, Any] | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT id, shop_id, email, password_hash, is_active, created_at, updated_at "
                    "FROM repair_shop_users WHERE email = :email"
                ),
                {"email": email.strip().lower()},
            ).fetchone()
        return row_to_dict(row) if row else None

    def verify_shop_user_password(self, email: str, password: str) -> dict[str, Any] | None:
        """Return public user dict on success, None on invalid credentials or inactive account."""
        row = self.get_shop_user_by_email(email)
        if row is None:
            return None
        if not row.get("is_active"):
            return None
        if not _verify_password(password, str(row["password_hash"])):
            return None
        # Return without password_hash
        return {k: v for k, v in row.items() if k != "password_hash"}

    def list_shop_users(
        self,
        shop_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List shop users, optionally filtered by shop_id. Returns (rows, total)."""
        with get_connection(self._db_path) as conn:
            if shop_id is not None:
                total = conn.execute(
                    text("SELECT COUNT(*) FROM repair_shop_users WHERE shop_id = :shop_id"),
                    {"shop_id": shop_id},
                ).scalar() or 0
                rows = conn.execute(
                    text(
                        "SELECT id, shop_id, email, is_active, created_at, updated_at "
                        "FROM repair_shop_users WHERE shop_id = :shop_id "
                        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                    ),
                    {"shop_id": shop_id, "limit": limit, "offset": offset},
                ).fetchall()
            else:
                total = conn.execute(
                    text("SELECT COUNT(*) FROM repair_shop_users"),
                ).scalar() or 0
                rows = conn.execute(
                    text(
                        "SELECT id, shop_id, email, is_active, created_at, updated_at "
                        "FROM repair_shop_users "
                        "ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
                    ),
                    {"limit": limit, "offset": offset},
                ).fetchall()
        return [row_to_dict(r) for r in rows], int(total)

    def deactivate_shop_user(self, user_id: str) -> bool:
        """Soft-delete (deactivate) a shop user. Returns True if found."""
        now = _utcnow_iso()
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text(
                    "UPDATE repair_shop_users SET is_active = 0, updated_at = :now WHERE id = :id"
                ),
                {"id": user_id, "now": now},
            )
        return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Claim assignments
    # ------------------------------------------------------------------

    def assign_claim_to_shop(
        self,
        claim_id: str,
        shop_id: str,
        *,
        assigned_by: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        """Create or return existing (claim_id, shop_id) assignment.

        Raises ValueError if the combination already exists.
        """
        now = _utcnow_iso()
        with get_connection(self._db_path) as conn:
            try:
                result = conn.execute(
                    text(
                        """
                        INSERT INTO repair_shop_claim_assignments
                            (claim_id, shop_id, assigned_by, notes, assigned_at)
                        VALUES (:claim_id, :shop_id, :assigned_by, :notes, :assigned_at)
                        RETURNING id
                        """
                    ),
                    {
                        "claim_id": claim_id,
                        "shop_id": shop_id,
                        "assigned_by": assigned_by,
                        "notes": notes,
                        "assigned_at": now,
                    },
                )
                row = result.fetchone()
                row_id = int(row[0]) if row else None
            except IntegrityError as e:
                raise ValueError(
                    f"Shop '{shop_id}' is already assigned to claim '{claim_id}'"
                ) from e
        return self.get_assignment_by_id(row_id)  # type: ignore[return-value]

    def get_assignment_by_id(self, assignment_id: int) -> dict[str, Any] | None:
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT id, claim_id, shop_id, assigned_by, notes, assigned_at "
                    "FROM repair_shop_claim_assignments WHERE id = :id"
                ),
                {"id": assignment_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_assignments_for_claim(self, claim_id: str) -> list[dict[str, Any]]:
        """Return all shop assignments for a given claim."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text(
                    "SELECT id, claim_id, shop_id, assigned_by, notes, assigned_at "
                    "FROM repair_shop_claim_assignments WHERE claim_id = :claim_id "
                    "ORDER BY assigned_at ASC"
                ),
                {"claim_id": claim_id},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_assignments_for_shop(
        self,
        shop_id: str,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Return all claim assignments for a given shop (paginated)."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text(
                    "SELECT id, claim_id, shop_id, assigned_by, notes, assigned_at "
                    "FROM repair_shop_claim_assignments WHERE shop_id = :shop_id "
                    "ORDER BY assigned_at DESC LIMIT :limit OFFSET :offset"
                ),
                {"shop_id": shop_id, "limit": limit, "offset": offset},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def count_assignments_for_shop(self, shop_id: str) -> int:
        """Return total number of claim assignments for a given shop."""
        with get_connection(self._db_path) as conn:
            return int(
                conn.execute(
                    text(
                        "SELECT COUNT(*) FROM repair_shop_claim_assignments "
                        "WHERE shop_id = :shop_id"
                    ),
                    {"shop_id": shop_id},
                ).scalar() or 0
            )

    def is_claim_assigned_to_shop(self, claim_id: str, shop_id: str) -> bool:
        """Return True if the given shop is assigned to the given claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT 1 FROM repair_shop_claim_assignments "
                    "WHERE claim_id = :claim_id AND shop_id = :shop_id LIMIT 1"
                ),
                {"claim_id": claim_id, "shop_id": shop_id},
            ).fetchone()
        return row is not None

    def remove_assignment(self, claim_id: str, shop_id: str) -> bool:
        """Remove a shop assignment from a claim. Returns True if it existed."""
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text(
                    "DELETE FROM repair_shop_claim_assignments "
                    "WHERE claim_id = :claim_id AND shop_id = :shop_id"
                ),
                {"claim_id": claim_id, "shop_id": shop_id},
            )
        return (result.rowcount or 0) > 0
