"""Tests for startup recovery of claims stuck in 'processing' status (H5)."""

import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import text

from claim_agent.config import reload_settings
from claim_agent.db.constants import STATUS_NEEDS_REVIEW, STATUS_PROCESSING
from claim_agent.db.database import get_connection, init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _insert_claim(conn, claim_id: str, status: str, updated_at: str) -> None:
    conn.execute(
        text(
            """
            INSERT INTO claims
                (id, policy_number, vin, incident_date, status, updated_at)
            VALUES
                (:id, :policy_number, :vin, :incident_date, :status, :updated_at)
            """
        ),
        {
            "id": claim_id,
            "policy_number": "POL-TEST",
            "vin": "1HGBH41JXMN109186",
            "incident_date": "2025-01-01",
            "status": status,
            "updated_at": updated_at,
        },
    )


def _fmt(dt: datetime) -> str:
    """Format datetime to SQLite-compatible string."""
    return dt.strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------------------------
# Repository method tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def recovery_db():
    """Temporary DB scoped to this test module."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    prev = os.environ.get("CLAIMS_DB_PATH")
    os.environ["CLAIMS_DB_PATH"] = path
    reload_settings()
    try:
        yield path
    finally:
        if prev is None:
            os.environ.pop("CLAIMS_DB_PATH", None)
        else:
            os.environ["CLAIMS_DB_PATH"] = prev
        try:
            os.unlink(path)
        except OSError:
            pass


class TestGetStuckProcessingClaims:
    """Unit tests for ClaimRepository.get_stuck_processing_claims."""

    def test_returns_empty_when_no_claims(self, recovery_db):
        repo = ClaimRepository(db_path=recovery_db)
        result = repo.get_stuck_processing_claims(stuck_after_minutes=30)
        assert result == []

    def test_returns_old_processing_claim(self, recovery_db):
        old_ts = _fmt(datetime.now(timezone.utc) - timedelta(hours=2))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-OLD-PROC", STATUS_PROCESSING, old_ts)

        repo = ClaimRepository(db_path=recovery_db)
        result = repo.get_stuck_processing_claims(stuck_after_minutes=30)

        assert len(result) == 1
        assert result[0]["id"] == "CLM-OLD-PROC"
        assert result[0]["status"] == STATUS_PROCESSING

    def test_ignores_recent_processing_claim(self, recovery_db):
        recent_ts = _fmt(datetime.now(timezone.utc) - timedelta(minutes=5))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-RECENT-PROC", STATUS_PROCESSING, recent_ts)

        repo = ClaimRepository(db_path=recovery_db)
        result = repo.get_stuck_processing_claims(stuck_after_minutes=30)
        assert result == []

    def test_ignores_non_processing_statuses(self, recovery_db):
        old_ts = _fmt(datetime.now(timezone.utc) - timedelta(hours=2))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-OPEN", "open", old_ts)
            _insert_claim(conn, "CLM-FAILED", "failed", old_ts)
            _insert_claim(conn, "CLM-NEEDS-REVIEW", STATUS_NEEDS_REVIEW, old_ts)

        repo = ClaimRepository(db_path=recovery_db)
        result = repo.get_stuck_processing_claims(stuck_after_minutes=30)
        assert result == []

    def test_returns_multiple_stuck_claims(self, recovery_db):
        old_ts = _fmt(datetime.now(timezone.utc) - timedelta(hours=1))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-STUCK-1", STATUS_PROCESSING, old_ts)
            _insert_claim(conn, "CLM-STUCK-2", STATUS_PROCESSING, old_ts)

        repo = ClaimRepository(db_path=recovery_db)
        result = repo.get_stuck_processing_claims(stuck_after_minutes=30)
        ids = {r["id"] for r in result}
        assert ids == {"CLM-STUCK-1", "CLM-STUCK-2"}

    def test_filters_by_cutoff_boundary(self, recovery_db):
        # Claim exactly at the boundary should be included (updated_at == cutoff)
        boundary_ts = _fmt(datetime.now(timezone.utc) - timedelta(minutes=30))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-BOUNDARY", STATUS_PROCESSING, boundary_ts)

        repo = ClaimRepository(db_path=recovery_db)
        result = repo.get_stuck_processing_claims(stuck_after_minutes=30)
        assert any(r["id"] == "CLM-BOUNDARY" for r in result)

    def test_returns_stuck_claim_with_iso8601_updated_at(self, recovery_db):
        """get_stuck_processing_claims must match .isoformat() updated_at (e.g. from lock)."""
        repo = ClaimRepository(db_path=recovery_db)
        inp = ClaimInput(
            policy_number="POL-ISO",
            vin="1HGBH41JXMN109099",
            vehicle_year=2022,
            vehicle_make="Toyota",
            vehicle_model="Camry",
            incident_date=date(2025, 3, 1),
            incident_description="Test",
            damage_description="Scratch",
        )
        claim_id = repo.create_claim(inp)
        repo.acquire_processing_lock(claim_id)
        old_iso = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        with get_connection(recovery_db) as conn:
            conn.execute(
                text("UPDATE claims SET updated_at = :ts WHERE id = :id"),
                {"ts": old_iso, "id": claim_id},
            )

        result = repo.get_stuck_processing_claims(stuck_after_minutes=30)
        assert any(r["id"] == claim_id for r in result)

    def test_raises_on_invalid_minutes(self, recovery_db):
        repo = ClaimRepository(db_path=recovery_db)
        with pytest.raises(ValueError):
            repo.get_stuck_processing_claims(stuck_after_minutes=0)


# ---------------------------------------------------------------------------
# Startup recovery function tests
# ---------------------------------------------------------------------------


class TestRecoverStuckProcessingClaims:
    """Tests for the _recover_stuck_processing_claims startup function."""

    def test_marks_stuck_claim_as_needs_review(self, recovery_db):
        old_ts = _fmt(datetime.now(timezone.utc) - timedelta(hours=2))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-RECOVER-1", STATUS_PROCESSING, old_ts)

        from claim_agent.api.server import _recover_stuck_processing_claims

        _recover_stuck_processing_claims()

        repo = ClaimRepository(db_path=recovery_db)
        claim = repo.get_claim("CLM-RECOVER-1")
        assert claim is not None
        assert claim["status"] == STATUS_NEEDS_REVIEW

    def test_recovery_writes_audit_trail(self, recovery_db):
        old_ts = _fmt(datetime.now(timezone.utc) - timedelta(hours=2))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-AUDIT", STATUS_PROCESSING, old_ts)

        from claim_agent.api.server import _recover_stuck_processing_claims

        _recover_stuck_processing_claims()

        repo = ClaimRepository(db_path=recovery_db)
        events, _ = repo.get_claim_history("CLM-AUDIT")
        assert any(
            e.get("new_status") == STATUS_NEEDS_REVIEW
            and "stuck" in (e.get("details") or "").lower()
            for e in events
        )

    def test_does_not_touch_recent_processing_claim(self, recovery_db):
        recent_ts = _fmt(datetime.now(timezone.utc) - timedelta(minutes=5))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-SKIP-1", STATUS_PROCESSING, recent_ts)

        from claim_agent.api.server import _recover_stuck_processing_claims

        _recover_stuck_processing_claims()

        repo = ClaimRepository(db_path=recovery_db)
        claim = repo.get_claim("CLM-SKIP-1")
        assert claim is not None
        assert claim["status"] == STATUS_PROCESSING

    def test_recovery_disabled_setting_skips_scan(self, recovery_db):
        old_ts = _fmt(datetime.now(timezone.utc) - timedelta(hours=2))
        with get_connection(recovery_db) as conn:
            _insert_claim(conn, "CLM-RECOVERY-OFF", STATUS_PROCESSING, old_ts)

        os.environ["CLAIM_AGENT_TASK_RECOVERY_ENABLED"] = "false"
        reload_settings()
        try:
            from claim_agent.api.server import _recover_stuck_processing_claims

            _recover_stuck_processing_claims()

            repo = ClaimRepository(db_path=recovery_db)
            claim = repo.get_claim("CLM-RECOVERY-OFF")
            assert claim is not None
            # Still processing because recovery was disabled
            assert claim["status"] == STATUS_PROCESSING
        finally:
            os.environ.pop("CLAIM_AGENT_TASK_RECOVERY_ENABLED", None)
            reload_settings()

    def test_no_stuck_claims_logs_debug(self, recovery_db, caplog):
        import logging

        from claim_agent.api.server import _recover_stuck_processing_claims

        with caplog.at_level(logging.DEBUG, logger="claim_agent.api.server"):
            _recover_stuck_processing_claims()

        assert any("no claims stuck" in m.lower() for m in caplog.messages)

    def test_db_error_is_caught_and_logged(self, recovery_db, caplog):
        import logging

        from claim_agent.api.server import _recover_stuck_processing_claims

        with (
            patch(
                "claim_agent.api.server.ClaimRepository.get_stuck_processing_claims",
                side_effect=RuntimeError("DB exploded"),
            ),
            caplog.at_level(logging.ERROR, logger="claim_agent.api.server"),
        ):
            # Should not raise
            _recover_stuck_processing_claims()

        assert any("stuck processing claims" in m.lower() for m in caplog.messages)
