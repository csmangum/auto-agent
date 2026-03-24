"""Repository for rental authorization persistence.

Persists structured rental arrangements when the rental crew completes.
The ``reimbursement_id`` acts as the idempotency key for the DB layer,
replacing the in-memory ``_IDEMPOTENCY_CACHE`` used in development/test runs
without a persistent ctx.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.engine import Connection

from claim_agent.db.database import get_connection, get_db_path, row_to_dict

# Allowed ``status`` values; enforced in Python and via CHECK in DDL (new DBs).
RENTAL_AUTHORIZATION_STATUSES = frozenset(
    {"authorized", "in_progress", "completed", "cancelled"}
)


def _validate_rental_status(status: str) -> None:
    if status not in RENTAL_AUTHORIZATION_STATUSES:
        allowed = ", ".join(sorted(RENTAL_AUTHORIZATION_STATUSES))
        raise ValueError(f"Invalid rental authorization status {status!r}; must be one of: {allowed}")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


# Fields that are safe to expose to claimants via the portal DTO.
# reservation_ref and agency_ref are intentionally excluded (vendor-sensitive /
# internal-only; not PII per se, but not appropriate for the self-service portal).
# Internal PK ``id`` is omitted to avoid leaking table cardinality.
_PORTAL_SAFE_FIELDS = frozenset(
    {
        "claim_id",
        "authorized_days",
        "daily_cap",
        "direct_bill",
        "status",
        "reimbursement_id",
        "amount_approved",
        "created_at",
        "updated_at",
    }
)


class RentalAuthorizationRepository:
    """Repository for rental authorization CRUD."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path if db_path is not None else get_db_path()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def upsert_authorization(
        self,
        claim_id: str,
        authorized_days: int,
        daily_cap: float,
        *,
        reservation_ref: str | None = None,
        agency_ref: str | None = None,
        direct_bill: bool = False,
        status: str = "authorized",
        reimbursement_id: str | None = None,
        amount_approved: float | None = None,
    ) -> int:
        """Insert or update the rental authorization for a claim.

        When ``reimbursement_id`` is set, only a row with that id is updated;
        otherwise a new row is inserted (so prior reimbursement IDs stay
        addressable). When ``reimbursement_id`` is omitted, the latest row for
        ``claim_id`` is updated if one exists, else a row is inserted.

        Returns the id of the inserted/updated row.
        """
        _validate_rental_status(status)
        now = _now_iso()

        with get_connection(self._db_path) as conn:
            existing_id = self._find_existing(conn, claim_id, reimbursement_id)

            if existing_id is not None:
                conn.execute(
                    text("""
                    UPDATE rental_authorizations
                    SET reservation_ref = :reservation_ref,
                        agency_ref      = :agency_ref,
                        authorized_days = :authorized_days,
                        daily_cap       = :daily_cap,
                        direct_bill     = :direct_bill,
                        status          = :status,
                        reimbursement_id = :reimbursement_id,
                        amount_approved = :amount_approved,
                        updated_at      = :now
                    WHERE id = :id
                    """),
                    {
                        "id": existing_id,
                        "reservation_ref": reservation_ref,
                        "agency_ref": agency_ref,
                        "authorized_days": authorized_days,
                        "daily_cap": daily_cap,
                        "direct_bill": 1 if direct_bill else 0,
                        "status": status,
                        "reimbursement_id": reimbursement_id,
                        "amount_approved": amount_approved,
                        "now": now,
                    },
                )
                return existing_id

            result = conn.execute(
                text("""
                INSERT INTO rental_authorizations
                    (claim_id, reservation_ref, agency_ref, authorized_days,
                     daily_cap, direct_bill, status, reimbursement_id,
                     amount_approved, created_at, updated_at)
                VALUES
                    (:claim_id, :reservation_ref, :agency_ref, :authorized_days,
                     :daily_cap, :direct_bill, :status, :reimbursement_id,
                     :amount_approved, :now, :now)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "reservation_ref": reservation_ref,
                    "agency_ref": agency_ref,
                    "authorized_days": authorized_days,
                    "daily_cap": daily_cap,
                    "direct_bill": 1 if direct_bill else 0,
                    "status": status,
                    "reimbursement_id": reimbursement_id,
                    "amount_approved": amount_approved,
                    "now": now,
                },
            )
            row = result.fetchone()
            return row[0] if row else 0

    def update_status(self, claim_id: str, status: str) -> bool:
        """Update the status of the most recent rental authorization for a claim.

        Returns True if a row was updated, False if no authorization exists.
        """
        _validate_rental_status(status)
        now = _now_iso()
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                UPDATE rental_authorizations
                SET status = :status, updated_at = :now
                WHERE id = (
                    SELECT id FROM rental_authorizations
                    WHERE claim_id = :claim_id
                    ORDER BY id DESC
                    LIMIT 1
                )
                """),
                {"status": status, "now": now, "claim_id": claim_id},
            )
            return (result.rowcount or 0) > 0

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_authorization(self, claim_id: str) -> dict[str, Any] | None:
        """Fetch the most recent rental authorization for a claim (internal view)."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("""
                SELECT id, claim_id, reservation_ref, agency_ref, authorized_days,
                       daily_cap, direct_bill, status, reimbursement_id,
                       amount_approved, created_at, updated_at
                FROM rental_authorizations
                WHERE claim_id = :claim_id
                ORDER BY id DESC
                LIMIT 1
                """),
                {"claim_id": claim_id},
            ).fetchone()
        if row is None:
            return None
        d = row_to_dict(row)
        # Normalize SQLite integer bool
        d["direct_bill"] = bool(d.get("direct_bill", 0))
        return d

    def get_portal_summary(self, claim_id: str) -> dict[str, Any] | None:
        """Fetch sanitized rental summary for the claimant portal.

        Excludes ``reservation_ref`` and ``agency_ref`` (vendor-sensitive /
        internal).  Returns None when no authorization has been persisted yet.
        """
        record = self.get_authorization(claim_id)
        if record is None:
            return None
        return {k: v for k, v in record.items() if k in _PORTAL_SAFE_FIELDS}

    def get_by_reimbursement_id(self, reimbursement_id: str) -> dict[str, Any] | None:
        """Fetch a rental authorization by its reimbursement_id (idempotency lookup)."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("""
                SELECT id, claim_id, reservation_ref, agency_ref, authorized_days,
                       daily_cap, direct_bill, status, reimbursement_id,
                       amount_approved, created_at, updated_at
                FROM rental_authorizations
                WHERE reimbursement_id = :rid
                LIMIT 1
                """),
                {"rid": reimbursement_id},
            ).fetchone()
        if row is None:
            return None
        d = row_to_dict(row)
        d["direct_bill"] = bool(d.get("direct_bill", 0))
        return d

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_existing(
        self, conn: Connection, claim_id: str, reimbursement_id: str | None
    ) -> int | None:
        """Return the id of an existing row to update, or None to insert."""
        if reimbursement_id:
            row = conn.execute(
                text("""
                SELECT id FROM rental_authorizations
                WHERE reimbursement_id = :rid
                LIMIT 1
                """),
                {"rid": reimbursement_id},
            ).fetchone()
            return cast(int, row[0]) if row else None
        row = conn.execute(
            text("""
            SELECT id FROM rental_authorizations
            WHERE claim_id = :claim_id
            ORDER BY id DESC LIMIT 1
            """),
            {"claim_id": claim_id},
        ).fetchone()
        return cast(int, row[0]) if row else None
