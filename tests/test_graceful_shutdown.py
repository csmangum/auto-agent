"""Tests for graceful shutdown of in-flight claim tasks (H11)."""

import asyncio
import os
import tempfile
from unittest.mock import patch

import pytest
from sqlalchemy import text

from claim_agent.config import reload_settings
from claim_agent.db.constants import STATUS_FAILED, STATUS_PROCESSING
from claim_agent.db.database import get_connection, init_db
from claim_agent.db.repository import ClaimRepository


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _insert_processing_claim(db_path: str, claim_id: str) -> None:
    """Insert a claim in processing state directly into the DB (avoids schema drift)."""
    with get_connection(db_path) as conn:
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
                "policy_number": "POL-GRACE-TEST",
                "vin": "1HGBH41JXMN109186",
                "incident_date": "2025-01-01",
                "status": STATUS_PROCESSING,
                "updated_at": "2025-01-01 00:00:00",
            },
        )


@pytest.fixture()
def grace_db():
    """Temporary SQLite DB for graceful-shutdown tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    # Add columns that are present in the real schema via Alembic migrations but
    # absent from the minimal init_db base schema. update_claim_status queries them.
    with get_connection(path) as conn:
        for stmt in (
            "ALTER TABLE claims ADD COLUMN settlement_agreed_at TEXT",
            "ALTER TABLE claims ADD COLUMN payment_due TEXT",
            "ALTER TABLE claims ADD COLUMN incident_latitude REAL",
            "ALTER TABLE claims ADD COLUMN incident_longitude REAL",
        ):
            try:
                conn.execute(text(stmt))
            except Exception as _exc:  # noqa: BLE001
                # Column may already exist; safe to ignore
                if "duplicate column" not in str(_exc).lower() and "already exists" not in str(_exc).lower():
                    raise
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
        reload_settings()
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Tests for _shutdown_background_tasks_with_grace
# ---------------------------------------------------------------------------


class TestShutdownBackgroundTasksWithGrace:
    """Unit tests for the graceful-shutdown helper."""

    @pytest.mark.asyncio
    async def test_no_tasks_returns_immediately(self):
        """When there are no in-flight tasks the helper is a no-op."""
        from claim_agent.api.server import _shutdown_background_tasks_with_grace

        with (
            patch("claim_agent.api.server.claim_background_tasks", set()),
            patch("claim_agent.api.server.claim_task_claim_ids", {}),
        ):
            # Should not raise or block
            await _shutdown_background_tasks_with_grace(grace_seconds=5)

    @pytest.mark.asyncio
    async def test_tasks_finishing_within_grace_period_are_awaited(self):
        """Tasks that complete within the grace window are awaited normally."""
        finished = []

        async def quick_task():
            await asyncio.sleep(0)
            finished.append(True)

        task = asyncio.create_task(quick_task())
        tasks_set = {task}
        task_ids = {task: "CLM-FAST"}

        from claim_agent.api.server import _shutdown_background_tasks_with_grace

        with (
            patch("claim_agent.api.server.claim_background_tasks", tasks_set),
            patch("claim_agent.api.server.claim_task_claim_ids", task_ids),
        ):
            await _shutdown_background_tasks_with_grace(grace_seconds=5)

        assert finished == [True]
        assert not task.cancelled()

    @pytest.mark.asyncio
    async def test_tasks_exceeding_grace_period_are_cancelled(self):
        """Tasks still running after the grace period are cancelled."""

        async def slow_task():
            await asyncio.sleep(9999)

        task = asyncio.create_task(slow_task())
        # Let the task start running
        await asyncio.sleep(0)

        tasks_set = {task}
        task_ids = {task: "CLM-SLOW"}

        from claim_agent.api.server import _shutdown_background_tasks_with_grace

        with (
            patch("claim_agent.api.server.claim_background_tasks", tasks_set),
            patch("claim_agent.api.server.claim_task_claim_ids", task_ids),
            patch("claim_agent.api.server.ClaimRepository"),
        ):
            await _shutdown_background_tasks_with_grace(grace_seconds=0)

        assert task.done()
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_interrupted_claim_marked_failed_with_recoverable_message(self, grace_db):
        """A claim whose task is cancelled is marked 'failed' with a recoverable message."""
        claim_id = "CLM-INTERRUPTED"
        _insert_processing_claim(grace_db, claim_id)

        async def slow_task():
            await asyncio.sleep(9999)

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)  # let the task start

        tasks_set = {task}
        task_ids = {task: claim_id}

        from claim_agent.api.server import _shutdown_background_tasks_with_grace

        with (
            patch("claim_agent.api.server.claim_background_tasks", tasks_set),
            patch("claim_agent.api.server.claim_task_claim_ids", task_ids),
        ):
            await _shutdown_background_tasks_with_grace(grace_seconds=0)

        assert task.cancelled()

        repo = ClaimRepository(db_path=grace_db)
        claim = repo.get_claim(claim_id)
        assert claim is not None
        assert claim["status"] == STATUS_FAILED

        # Audit trail should include the recoverable detail message
        events, _ = repo.get_claim_history(claim_id)
        recoverable_events = [
            e for e in events
            if e.get("new_status") == STATUS_FAILED
            and "recoverable" in (e.get("details") or "").lower()
        ]
        assert recoverable_events, "Expected a 'failed' audit event with 'recoverable' in details"

    @pytest.mark.asyncio
    async def test_grace_period_zero_cancels_immediately(self):
        """grace_seconds=0 cancels tasks without any wait."""
        task_started = asyncio.Event()

        async def never_ending():
            task_started.set()
            await asyncio.sleep(9999)

        task = asyncio.create_task(never_ending())
        await task_started.wait()  # ensure task is actually running

        tasks_set = {task}
        task_ids = {task: "CLM-IMMEDIATE"}

        from claim_agent.api.server import _shutdown_background_tasks_with_grace

        with (
            patch("claim_agent.api.server.claim_background_tasks", tasks_set),
            patch("claim_agent.api.server.claim_task_claim_ids", task_ids),
            patch("claim_agent.api.server.ClaimRepository"),
        ):
            await _shutdown_background_tasks_with_grace(grace_seconds=0)

        assert task.done()
        assert task.cancelled()

    @pytest.mark.asyncio
    async def test_db_error_during_marking_is_caught(self, grace_db, caplog):
        """DB errors when marking a claim as failed are logged and do not raise."""
        import logging

        async def slow_task():
            await asyncio.sleep(9999)

        task = asyncio.create_task(slow_task())
        await asyncio.sleep(0)

        tasks_set = {task}
        task_ids = {task: "CLM-DB-ERR"}

        from claim_agent.api.server import _shutdown_background_tasks_with_grace

        with (
            patch("claim_agent.api.server.claim_background_tasks", tasks_set),
            patch("claim_agent.api.server.claim_task_claim_ids", task_ids),
            patch(
                "claim_agent.api.server.ClaimRepository.update_claim_status",
                side_effect=RuntimeError("DB error"),
            ),
            caplog.at_level(logging.ERROR, logger="claim_agent.api.server"),
        ):
            # Must not raise despite the DB error
            await _shutdown_background_tasks_with_grace(grace_seconds=0)

        assert task.done()
        assert task.cancelled()
        assert any("failed to mark claim" in m.lower() for m in caplog.messages)


# ---------------------------------------------------------------------------
# Settings: shutdown_grace_period_seconds
# ---------------------------------------------------------------------------


class TestShutdownGracePeriodSetting:
    """The new setting is exposed via Settings."""

    def test_default_value(self):
        from claim_agent.config import get_settings

        settings = get_settings()
        assert settings.shutdown_grace_period_seconds == 30

    def test_overridden_by_env_var(self):
        os.environ["CLAIM_AGENT_SHUTDOWN_GRACE_SECONDS"] = "60"
        reload_settings()
        try:
            from claim_agent.config import get_settings

            settings = get_settings()
            assert settings.shutdown_grace_period_seconds == 60
        finally:
            os.environ.pop("CLAIM_AGENT_SHUTDOWN_GRACE_SECONDS", None)
            reload_settings()

    def test_zero_is_valid(self):
        os.environ["CLAIM_AGENT_SHUTDOWN_GRACE_SECONDS"] = "0"
        reload_settings()
        try:
            from claim_agent.config import get_settings

            settings = get_settings()
            assert settings.shutdown_grace_period_seconds == 0
        finally:
            os.environ.pop("CLAIM_AGENT_SHUTDOWN_GRACE_SECONDS", None)
            reload_settings()
