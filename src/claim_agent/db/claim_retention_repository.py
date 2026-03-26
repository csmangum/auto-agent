"""Claim retention repository: retention lifecycle, archive, purge, and cold-storage export.

Implements the full data-retention lifecycle:
  list_claims_for_retention → archive_claim → list_claims_for_purge → purge_claim
  → cold-storage export helpers → audit-log retention helpers
"""

import calendar
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import text

from claim_agent.db.audit_events import (
    ACTOR_RETENTION,
    ACTOR_WORKFLOW,
    AUDIT_EVENT_LITIGATION_HOLD,
    AUDIT_EVENT_RETENTION,
    AUDIT_EVENT_RETENTION_PURGED,
)
from claim_agent.db.constants import (
    RETENTION_TIER_ARCHIVED,
    RETENTION_TIER_PURGED,
    STATUS_ARCHIVED,
    STATUS_CLOSED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PENDING_INFO,
    STATUS_PROCESSING,
    STATUS_PURGED,
)
from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.db.pii_redaction import anonymize_claim_pii
from claim_agent.db.state_machine import validate_transition
from claim_agent.events import ClaimEvent, emit_claim_event
from claim_agent.exceptions import ClaimNotFoundError, DomainValidationError
from claim_agent.config import get_settings
from claim_agent.rag.constants import normalize_state


# ---------------------------------------------------------------------------
# Module-level helpers (also re-exported for use in repository.py)
# ---------------------------------------------------------------------------

def _to_utc_aware(dt: datetime) -> datetime:
    """Ensure *dt* is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _add_calendar_years(dt: datetime, years: int) -> datetime:
    """Return ``dt`` plus ``years`` calendar years (clamp day for short months, e.g. Feb 29)."""
    new_year = dt.year + years
    month = dt.month
    last_day = calendar.monthrange(new_year, month)[1]
    new_day = min(dt.day, last_day)
    return dt.replace(year=new_year, month=month, day=new_day)


def _is_claim_past_retention(
    row_d: dict[str, Any],
    now: datetime,
    retention_period_years: int,
    retention_by_state: dict[str, int],
) -> bool:
    """Return True if claim's created_at is past its retention cutoff.

    Uses loss_state to pick per-state retention when retention_by_state is non-empty;
    falls back to retention_period_years when state is missing or not in map.
    """
    raw_state = (row_d.get("loss_state") or "").strip()
    lookup_state: str | None = None
    if raw_state:
        try:
            lookup_state = normalize_state(raw_state)
        except ValueError:
            pass
    state_years = retention_by_state.get(lookup_state) if lookup_state else None
    years = retention_period_years if state_years is None else state_years
    cutoff_dt = now - timedelta(days=years * 365)
    created_raw = row_d.get("created_at")
    if not created_raw:
        return True
    created_dt: datetime
    if isinstance(created_raw, datetime):
        created_dt = created_raw
    elif isinstance(created_raw, str):
        try:
            created_dt = datetime.fromisoformat(created_raw)
        except ValueError:
            try:
                created_dt = datetime.strptime(created_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return True
    else:
        return True

    return _to_utc_aware(created_dt) <= _to_utc_aware(cutoff_dt)


def _is_archived_past_purge_period(
    row_d: dict[str, Any],
    now: datetime,
    purge_after_archive_years: int,
    purge_by_state: dict[str, int] | None = None,
) -> bool:
    """True if ``now`` is on or after the calendar anniversary of archived_at + N years.

    When ``purge_by_state`` is set, uses the entry for the normalized ``loss_state`` if present;
    otherwise uses ``purge_after_archive_years``. A non-empty map does not override unknown states.
    """
    if purge_after_archive_years < 0:
        raise ValueError("purge_after_archive_years must be non-negative")
    archived_raw = row_d.get("archived_at")
    if not archived_raw:
        return False

    state_map = purge_by_state or {}
    raw_state = (row_d.get("loss_state") or "").strip()
    lookup_state: str | None = None
    if raw_state:
        try:
            lookup_state = normalize_state(raw_state)
        except ValueError:
            pass
    state_years = state_map.get(lookup_state) if lookup_state else None
    if state_years is not None and state_years < 0:
        raise ValueError("per-state purge_after_archive years must be non-negative")
    years = purge_after_archive_years if state_years is None else state_years

    archived_dt: datetime
    if isinstance(archived_raw, datetime):
        archived_dt = archived_raw
    elif isinstance(archived_raw, str):
        try:
            archived_dt = datetime.fromisoformat(archived_raw)
        except ValueError:
            try:
                archived_dt = datetime.strptime(archived_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return False
    else:
        return False

    cutoff = _add_calendar_years(_to_utc_aware(archived_dt), years)
    return _to_utc_aware(now) >= cutoff


def _is_purged_past_audit_retention_period(
    row_d: dict[str, Any],
    now: datetime,
    audit_retention_years_after_purge: int,
) -> bool:
    """True if ``now`` is on or after purged_at + N calendar years (claim must be purged)."""
    if audit_retention_years_after_purge < 0:
        raise ValueError("audit_retention_years_after_purge must be non-negative")
    purged_raw = row_d.get("purged_at")
    if not purged_raw:
        return False

    purged_dt: datetime
    if isinstance(purged_raw, datetime):
        purged_dt = purged_raw
    elif isinstance(purged_raw, str):
        try:
            purged_dt = datetime.fromisoformat(purged_raw)
        except ValueError:
            try:
                purged_dt = datetime.strptime(purged_raw, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return False
    else:
        return False

    cutoff = _add_calendar_years(_to_utc_aware(purged_dt), audit_retention_years_after_purge)
    return _to_utc_aware(now) >= cutoff


def _sql_in_params(prefix: str, ids: list[str]) -> tuple[str, dict[str, Any]]:
    """Build ``IN (:p0,:p1,...)`` fragment and param dict."""
    if not ids:
        return "", {}
    keys = [f"{prefix}{i}" for i in range(len(ids))]
    placeholders = ",".join(f":{k}" for k in keys)
    params = dict(zip(keys, ids, strict=True))
    return placeholders, params


# ---------------------------------------------------------------------------
# Repository class
# ---------------------------------------------------------------------------

class ClaimRetentionRepository:
    """Repository for claim retention lifecycle management: archive, purge, cold-storage export,
    and audit log retention helpers."""

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path

    def list_claims_for_retention(
        self,
        retention_period_years: int,
        *,
        retention_by_state: dict[str, int] | None = None,
        exclude_litigation_hold: bool = True,
    ) -> list[dict[str, Any]]:
        """List closed claims older than retention period that are not yet archived.

        Uses created_at for cutoff. Only returns claims with status closed
        (archiving requires closed->archived transition). Excludes claims
        with status archived or a non-null archived_at.

        When exclude_litigation_hold is True (default), claims with
        litigation_hold=1 are excluded (retention suspended for litigation).

        When retention_by_state is provided, uses loss_state to pick per-claim
        retention; falls back to retention_period_years when state is missing
        or not in the map.
        """
        if retention_period_years < 0:
            raise ValueError("retention_period_years must be non-negative")
        state_map = retention_by_state or {}
        now = datetime.now(timezone.utc)
        cutoff_dt = now - timedelta(days=retention_period_years * 365)
        cutoff = cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")

        if state_map:
            min_state_years = min(state_map.values())
            min_retention_years = min(retention_period_years, min_state_years)
            coarse_cutoff_dt = now - timedelta(days=min_retention_years * 365)
            coarse_cutoff = coarse_cutoff_dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            coarse_cutoff = cutoff

        with get_connection(self._db_path) as conn:
            if not state_map:
                rows = conn.execute(
                    text("""
                    SELECT * FROM claims
                    WHERE archived_at IS NULL
                      AND status = :status
                      AND created_at <= :cutoff
                      AND (COALESCE(litigation_hold, 0) = 0 OR :include_hold = 1)
                    ORDER BY created_at ASC
                    """),
                    {
                        "status": STATUS_CLOSED,
                        "cutoff": cutoff,
                        "include_hold": 1 if not exclude_litigation_hold else 0,
                    },
                ).fetchall()
                return [row_to_dict(r) for r in rows]

            rows = conn.execute(
                text("""
                SELECT * FROM claims
                WHERE archived_at IS NULL
                  AND status = :status
                  AND created_at <= :cutoff
                  AND (COALESCE(litigation_hold, 0) = 0 OR :include_hold = 1)
                ORDER BY created_at ASC
                """),
                {
                    "status": STATUS_CLOSED,
                    "cutoff": coarse_cutoff,
                    "include_hold": 1 if not exclude_litigation_hold else 0,
                },
            ).fetchall()

        result = []
        for r in rows:
            row_d = row_to_dict(r)
            if _is_claim_past_retention(row_d, now, retention_period_years, state_map):
                result.append(row_d)
        return result

    def set_litigation_hold(
        self,
        claim_id: str,
        litigation_hold: bool,
        *,
        actor_id: str = ACTOR_WORKFLOW,
    ) -> None:
        """Set or clear litigation hold on a claim. Logs to audit."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT id, litigation_hold FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            current = 1 if row_d.get("litigation_hold") else 0
            new_val = 1 if litigation_hold else 0
            if current == new_val:
                return
            conn.execute(
                text("""
                UPDATE claims SET litigation_hold = :val, updated_at = CURRENT_TIMESTAMP
                WHERE id = :claim_id
                """),
                {"claim_id": claim_id, "val": new_val},
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_LITIGATION_HOLD,
                    "details": "Litigation hold set"
                    if litigation_hold
                    else "Litigation hold cleared",
                    "actor_id": actor_id,
                },
            )

    def retention_report(
        self,
        retention_period_years: int,
        *,
        retention_by_state: dict[str, int] | None = None,
        purge_after_archive_years: int = 2,
        purge_by_state: dict[str, int] | None = None,
        audit_log_retention_years_after_purge: int | None = None,
        exclude_litigation_hold_from_audit_eligibility: bool = True,
    ) -> dict[str, Any]:
        """Produce retention audit report: counts by tier, litigation hold, pending archive/purge."""
        state_map = retention_by_state or {}
        purge_state_map = purge_by_state or {}
        now = datetime.now(timezone.utc)

        with get_connection(self._db_path) as conn:
            status_rows = conn.execute(
                text("""
                SELECT status, COUNT(*) as cnt FROM claims GROUP BY status
                """)
            ).fetchall()
            status_counts = {r[0]: r[1] for r in status_rows}

            tier_rows = conn.execute(
                text("""
                SELECT retention_tier, COUNT(*) as cnt FROM claims GROUP BY retention_tier
                """)
            ).fetchall()
            claims_by_retention_tier = {r[0]: r[1] for r in tier_rows}

            litigation_hold_count = (
                conn.execute(
                    text("SELECT COUNT(*) FROM claims WHERE COALESCE(litigation_hold, 0) = 1")
                ).scalar()
                or 0
            )

            audit_count = conn.execute(text("SELECT COUNT(*) FROM claim_audit_log")).scalar() or 0

            audit_rows_for_purged_claims = (
                conn.execute(
                    text("""
                    SELECT COUNT(*) FROM claim_audit_log AS a
                    INNER JOIN claims AS c ON c.id = a.claim_id
                    WHERE c.status = :st
                    """),
                    {"st": STATUS_PURGED},
                ).scalar()
                or 0
            )
            audit_rows_for_non_purged_claims = max(0, audit_count - audit_rows_for_purged_claims)

            audit_rows_eligible_for_retention: int | None = None
            if audit_log_retention_years_after_purge is not None:
                purged_claim_rows = conn.execute(
                    text("""
                    SELECT id, purged_at, litigation_hold
                    FROM claims
                    WHERE status = :st AND purged_at IS NOT NULL
                    """),
                    {"st": STATUS_PURGED},
                ).fetchall()
                eligible_ids: list[str] = []
                for r in purged_claim_rows:
                    row_d = row_to_dict(r)
                    if exclude_litigation_hold_from_audit_eligibility and row_d.get(
                        "litigation_hold"
                    ):
                        continue
                    if _is_purged_past_audit_retention_period(
                        row_d, now, audit_log_retention_years_after_purge
                    ):
                        eligible_ids.append(str(row_d["id"]))
                audit_rows_eligible_for_retention = 0
                chunk_size = 400
                for i in range(0, len(eligible_ids), chunk_size):
                    chunk = eligible_ids[i : i + chunk_size]
                    placeholders, in_params = _sql_in_params("ac_", chunk)
                    audit_rows_eligible_for_retention += (
                        conn.execute(
                            text(
                                f"SELECT COUNT(*) FROM claim_audit_log WHERE claim_id IN ({placeholders})"
                            ),
                            in_params,
                        ).scalar()
                        or 0
                    )

            closed_rows = conn.execute(
                text("""
                SELECT id, created_at, loss_state, litigation_hold
                FROM claims WHERE status = :status AND archived_at IS NULL
                """),
                {"status": STATUS_CLOSED},
            ).fetchall()

            archived_rows = conn.execute(
                text("""
                SELECT id, archived_at, loss_state, litigation_hold FROM claims
                WHERE status = :st AND archived_at IS NOT NULL
                """),
                {"st": STATUS_ARCHIVED},
            ).fetchall()

        pending_archive = 0
        for r in closed_rows:
            row_d = row_to_dict(r)
            if row_d.get("litigation_hold"):
                continue
            if _is_claim_past_retention(row_d, now, retention_period_years, state_map):
                pending_archive += 1

        closed_with_hold = sum(1 for r in closed_rows if row_to_dict(r).get("litigation_hold"))

        pending_purge = 0
        for r in archived_rows:
            row_d = row_to_dict(r)
            if row_d.get("litigation_hold"):
                continue
            if _is_archived_past_purge_period(
                row_d, now, purge_after_archive_years, purge_state_map
            ):
                pending_purge += 1

        return {
            "retention_period_years": retention_period_years,
            "purge_after_archive_years": purge_after_archive_years,
            "retention_by_state": state_map,
            "purge_by_state": purge_state_map,
            "claims_by_status": status_counts,
            "claims_by_retention_tier": claims_by_retention_tier,
            "active_count": sum(
                status_counts.get(s, 0)
                for s in (
                    STATUS_PENDING,
                    STATUS_PROCESSING,
                    STATUS_NEEDS_REVIEW,
                    STATUS_PENDING_INFO,
                )
            ),
            "closed_count": status_counts.get(STATUS_CLOSED, 0),
            "archived_count": status_counts.get(STATUS_ARCHIVED, 0),
            "purged_count": status_counts.get(STATUS_PURGED, 0),
            "litigation_hold_count": litigation_hold_count,
            "closed_with_litigation_hold": closed_with_hold,
            "pending_archive_count": pending_archive,
            "pending_purge_count": pending_purge,
            "audit_log_rows": audit_count,
            "audit_log_rows_for_purged_claims": audit_rows_for_purged_claims,
            "audit_log_rows_for_non_purged_claims": audit_rows_for_non_purged_claims,
            "audit_log_retention_years_after_purge": audit_log_retention_years_after_purge,
            "audit_log_rows_eligible_for_retention": audit_rows_eligible_for_retention,
        }

    def archive_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Archive a claim (soft delete for retention). Sets archived_at and status=archived."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT status, claim_type, payout_amount FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            old_status = row_d["status"]
            if old_status == STATUS_ARCHIVED:
                return
            if old_status == STATUS_PURGED:
                return
            validate_transition(
                claim_id,
                old_status,
                STATUS_ARCHIVED,
                claim=row_d,
                actor_id=actor_id,
            )
            conn.execute(
                text("""
                UPDATE claims SET status = :status, archived_at = CURRENT_TIMESTAMP,
                retention_tier = :rtier, updated_at = CURRENT_TIMESTAMP
                WHERE id = :claim_id
                """),
                {
                    "status": STATUS_ARCHIVED,
                    "rtier": RETENTION_TIER_ARCHIVED,
                    "claim_id": claim_id,
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_RETENTION,
                    "old_status": old_status,
                    "new_status": STATUS_ARCHIVED,
                    "details": "Archived for retention (claim older than retention period)",
                    "actor_id": actor_id,
                },
            )

        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=STATUS_ARCHIVED,
                summary="Archived for retention",
                claim_type=row_d["claim_type"],
                payout_amount=row_d["payout_amount"],
            )
        )

    def list_claims_for_purge(
        self,
        purge_after_archive_years: int,
        *,
        purge_by_state: dict[str, int] | None = None,
        exclude_litigation_hold: bool = True,
    ) -> list[dict[str, Any]]:
        """List archived claims past purge horizon (archived_at + N calendar years)."""
        if purge_after_archive_years < 0:
            raise ValueError("purge_after_archive_years must be non-negative")
        now = datetime.now(timezone.utc)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT * FROM claims
                WHERE status = :st
                  AND archived_at IS NOT NULL
                  AND (COALESCE(litigation_hold, 0) = 0 OR :include_hold = 1)
                ORDER BY archived_at ASC
                """),
                {
                    "st": STATUS_ARCHIVED,
                    "include_hold": 1 if not exclude_litigation_hold else 0,
                },
            ).fetchall()
        result = []
        for r in rows:
            row_d = row_to_dict(r)
            if _is_archived_past_purge_period(
                row_d, now, purge_after_archive_years, purge_by_state
            ):
                result.append(row_d)
        return result

    def purge_claim(
        self,
        claim_id: str,
        *,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Purge for retention: anonymize PII, status purged, retention_tier purged."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT status, claim_type, payout_amount FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            row_d = row_to_dict(row)
            old_status = row_d["status"]
            if old_status == STATUS_PURGED:
                return
            validate_transition(
                claim_id,
                old_status,
                STATUS_PURGED,
                claim=row_d,
                actor_id=actor_id,
            )
            anonymize_claim_pii(
                conn,
                claim_id,
                now_iso=now_iso,
                notes_redaction_text="[REDACTED - retention purge]",
                redact_audit_log=get_settings().privacy.audit_log_state_redaction_enabled,
            )
            conn.execute(
                text("""
                UPDATE claims SET status = :status, retention_tier = :rtier,
                purged_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE id = :claim_id
                """),
                {
                    "status": STATUS_PURGED,
                    "rtier": RETENTION_TIER_PURGED,
                    "claim_id": claim_id,
                },
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log (claim_id, action, old_status, new_status, details, actor_id)
                VALUES (:claim_id, :action, :old_status, :new_status, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_RETENTION_PURGED,
                    "old_status": old_status,
                    "new_status": STATUS_PURGED,
                    "details": "Purged for retention (PII anonymized; audit trail retained)",
                    "actor_id": actor_id,
                },
            )

        emit_claim_event(
            ClaimEvent(
                claim_id=claim_id,
                status=STATUS_PURGED,
                summary="Purged for retention",
                claim_type=row_d["claim_type"],
                payout_amount=row_d["payout_amount"],
            )
        )

    # ------------------------------------------------------------------
    # Cold-storage export helpers
    # ------------------------------------------------------------------

    def get_cold_storage_export_key(self, claim_id: str) -> str | None:
        """Return the S3 key if this claim has already been exported, else None."""
        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text(
                    "SELECT cold_storage_export_key FROM claims WHERE id = :claim_id"
                    " AND cold_storage_exported_at IS NOT NULL"
                ),
                {"claim_id": claim_id},
            ).fetchone()
        if row is None:
            return None
        return row_to_dict(row).get("cold_storage_export_key")

    def list_claims_for_export(
        self,
        purge_after_archive_years: int,
        *,
        purge_by_state: dict[str, int] | None = None,
        exclude_litigation_hold: bool = True,
    ) -> list[dict[str, Any]]:
        """List archived claims eligible for cold-storage export.

        Eligible claims are those that:
        - have ``status = 'archived'`` and ``archived_at`` set,
        - are past the purge horizon (same logic as :meth:`list_claims_for_purge`), and
        - have **not** yet been exported (``cold_storage_exported_at IS NULL``).

        Args:
            purge_after_archive_years: Years after ``archived_at`` before export is due.
            purge_by_state: Optional per-state override map (state name → years).
            exclude_litigation_hold: When True (default), claims with a litigation hold
                are excluded.

        Returns:
            List of claim dicts eligible for export.
        """
        if purge_after_archive_years < 0:
            raise ValueError("purge_after_archive_years must be non-negative")
        now = datetime.now(timezone.utc)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT * FROM claims
                WHERE status = :st
                  AND archived_at IS NOT NULL
                  AND cold_storage_exported_at IS NULL
                  AND (COALESCE(litigation_hold, 0) = 0 OR :include_hold = 1)
                ORDER BY archived_at ASC
                """),
                {
                    "st": STATUS_ARCHIVED,
                    "include_hold": 1 if not exclude_litigation_hold else 0,
                },
            ).fetchall()
        result = []
        for r in rows:
            row_d = row_to_dict(r)
            if _is_archived_past_purge_period(
                row_d, now, purge_after_archive_years, purge_by_state
            ):
                result.append(row_d)
        return result

    def mark_claim_exported(
        self,
        claim_id: str,
        export_key: str,
        actor_id: str = ACTOR_RETENTION,
    ) -> None:
        """Record that a claim has been exported to cold storage.

        Sets ``cold_storage_exported_at`` and ``cold_storage_export_key`` on the
        claim row and appends a ``cold_storage_exported`` audit log entry.

        Args:
            claim_id: Claim to mark as exported.
            export_key: S3 object key of the uploaded manifest.
            actor_id: Actor identifier for the audit log.

        Raises:
            ClaimNotFoundError: If the claim does not exist.
        """
        from claim_agent.db.audit_events import AUDIT_EVENT_COLD_STORAGE_EXPORTED

        with get_connection(self._db_path) as conn:
            row = conn.execute(
                text("SELECT status FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if row is None:
                raise ClaimNotFoundError(f"Claim not found: {claim_id}")
            conn.execute(
                text("""
                UPDATE claims
                SET cold_storage_exported_at = CURRENT_TIMESTAMP,
                    cold_storage_export_key = :export_key,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = :claim_id
                """),
                {"export_key": export_key, "claim_id": claim_id},
            )
            conn.execute(
                text("""
                INSERT INTO claim_audit_log
                    (claim_id, action, details, actor_id)
                VALUES (:claim_id, :action, :details, :actor_id)
                """),
                {
                    "claim_id": claim_id,
                    "action": AUDIT_EVENT_COLD_STORAGE_EXPORTED,
                    "details": f"Exported to cold storage: {export_key}",
                    "actor_id": actor_id,
                },
            )

    # ------------------------------------------------------------------
    # Audit log retention helpers
    # ------------------------------------------------------------------

    def list_claim_ids_eligible_for_audit_log_retention(
        self,
        audit_retention_years_after_purge: int,
        *,
        exclude_litigation_hold: bool = True,
    ) -> list[str]:
        """Claim IDs (status purged) past purged_at + N calendar years for audit export/purge."""
        if audit_retention_years_after_purge < 0:
            raise ValueError("audit_retention_years_after_purge must be non-negative")
        now = datetime.now(timezone.utc)
        with get_connection(self._db_path) as conn:
            rows = conn.execute(
                text("""
                SELECT id, purged_at, litigation_hold
                FROM claims
                WHERE status = :st AND purged_at IS NOT NULL
                ORDER BY id ASC
                """),
                {"st": STATUS_PURGED},
            ).fetchall()
        eligible: list[str] = []
        for r in rows:
            row_d = row_to_dict(r)
            if exclude_litigation_hold and row_d.get("litigation_hold"):
                continue
            if _is_purged_past_audit_retention_period(
                row_d, now, audit_retention_years_after_purge
            ):
                eligible.append(str(row_d["id"]))
        return eligible

    def fetch_audit_log_rows_for_claim_ids(
        self, claim_ids: list[str], *, chunk_size: int = 400
    ) -> list[dict[str, Any]]:
        """Return audit log rows for the given claim IDs (ordered by claim_id, id)."""
        if not claim_ids:
            return []
        out: list[dict[str, Any]] = []
        with get_connection(self._db_path) as conn:
            for i in range(0, len(claim_ids), chunk_size):
                chunk = claim_ids[i : i + chunk_size]
                placeholders, in_params = _sql_in_params("ex_", chunk)
                rows = conn.execute(
                    text(
                        f"""
                        SELECT * FROM claim_audit_log
                        WHERE claim_id IN ({placeholders})
                        ORDER BY claim_id ASC, id ASC
                        """
                    ),
                    in_params,
                ).fetchall()
                out.extend(row_to_dict(r) for r in rows)
        return out

    def count_audit_log_rows_for_claim_ids(
        self, claim_ids: list[str], *, chunk_size: int = 400
    ) -> int:
        """Count claim_audit_log rows whose claim_id is in claim_ids."""
        if not claim_ids:
            return 0
        total = 0
        with get_connection(self._db_path) as conn:
            for i in range(0, len(claim_ids), chunk_size):
                chunk = claim_ids[i : i + chunk_size]
                placeholders, in_params = _sql_in_params("cn_", chunk)
                total += (
                    conn.execute(
                        text(
                            f"SELECT COUNT(*) FROM claim_audit_log WHERE claim_id IN ({placeholders})"
                        ),
                        in_params,
                    ).scalar()
                    or 0
                )
        return total

    def purge_audit_log_for_claim_ids(
        self,
        claim_ids: list[str],
        *,
        audit_purge_enabled: bool,
        chunk_size: int = 400,
    ) -> int:
        """Delete claim_audit_log rows for claim_ids. Requires AUDIT_LOG_PURGE_ENABLED."""
        if not audit_purge_enabled:
            raise DomainValidationError(
                "Audit log purge is disabled; set AUDIT_LOG_PURGE_ENABLED=true after compliance approval"
            )
        if not claim_ids:
            return 0
        deleted = 0
        with get_connection(self._db_path) as conn:
            for i in range(0, len(claim_ids), chunk_size):
                chunk = claim_ids[i : i + chunk_size]
                placeholders, in_params = _sql_in_params("dl_", chunk)
                result = conn.execute(
                    text(f"DELETE FROM claim_audit_log WHERE claim_id IN ({placeholders})"),
                    in_params,
                )
                raw = result.rowcount
                deleted += int(raw) if raw is not None else 0
        return deleted
