"""Repository for repair status tracking (partial loss repair progress)."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from claim_agent.db.database import get_connection, get_db_path, row_to_dict


def parse_iso_ts(ts: str | None) -> datetime | None:
    """Parse ISO timestamp; return None if invalid."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class RepairStatusRepository:
    """Repository for repair status persistence."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path if db_path is not None else get_db_path()

    def insert_repair_status(
        self,
        claim_id: str,
        shop_id: str,
        status: str,
        *,
        authorization_id: str | None = None,
        notes: str | None = None,
        paused_at: str | None = None,
        pause_reason: str | None = None,
    ) -> int:
        """Insert a new repair status record (append-only history).

        Returns the id of the inserted row.
        """
        now = _now_iso()
        with get_connection(self._db_path) as conn:
            result = conn.execute(
                text("""
                INSERT INTO repair_status
                    (claim_id, shop_id, authorization_id, status, status_updated_at,
                     notes, paused_at, pause_reason, updated_at)
                VALUES (:claim_id, :shop_id, :auth_id, :status, :now,
                        :notes, :paused_at, :pause_reason, :now2)
                RETURNING id
                """),
                {
                    "claim_id": claim_id,
                    "shop_id": shop_id,
                    "auth_id": authorization_id or None,
                    "status": status,
                    "now": now,
                    "notes": notes or None,
                    "paused_at": paused_at or None,
                    "pause_reason": pause_reason or None,
                    "now2": now,
                },
            )
            row = result.fetchone()
            return row[0] if row else 0

    def get_repair_status(self, claim_id: str) -> dict[str, Any] | None:
        """Fetch the latest repair status for a claim."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("""
                SELECT id, claim_id, shop_id, authorization_id, status,
                       status_updated_at, notes, paused_at, pause_reason,
                       created_at, updated_at
                FROM repair_status
                WHERE claim_id = :claim_id
                ORDER BY id DESC
                LIMIT 1
                """),
                {"claim_id": claim_id},
            ).fetchone()
        return row_to_dict(row) if row else None

    def get_repair_status_history(
        self,
        claim_id: str,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch repair status history for a claim, oldest first (for cycle time)."""
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT id, claim_id, shop_id, authorization_id, status,
                       status_updated_at, notes, paused_at, pause_reason,
                       created_at, updated_at
                FROM repair_status
                WHERE claim_id = :claim_id
                ORDER BY id ASC
                LIMIT :limit
                """),
                {"claim_id": claim_id, "limit": limit},
            ).fetchall()
        return [row_to_dict(r) for r in rows]

    def get_cycle_time_days(self, claim_id: str) -> float | None:
        """Compute repair cycle time in days: from first 'received' to first 'ready'.

        Returns None if we don't have both received and ready in history.
        """
        history = self.get_repair_status_history(claim_id)
        received_ts: datetime | None = None
        ready_ts: datetime | None = None
        for h in history:
            status = (h.get("status") or "").strip()
            ts = parse_iso_ts(h.get("status_updated_at"))
            if not ts:
                continue
            if status == "received" and received_ts is None:
                received_ts = ts
            if status == "ready" and ready_ts is None:
                ready_ts = ts
            if received_ts and ready_ts:
                break
        if received_ts is None or ready_ts is None:
            return None
        delta = ready_ts - received_ts
        return round(delta.total_seconds() / 86400.0, 1)
