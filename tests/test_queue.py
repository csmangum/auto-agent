"""Unit tests for async job queue and task logic."""

import os
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.db.constants import STATUS_PENDING, STATUS_QUEUED
from claim_agent.db.database import get_connection
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.queue.queue import (
    _record_job_claim_mapping,
    _update_job_status,
    get_job_id_for_claim,
    get_job_status,
    is_queue_available,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_CLAIM = {
    "policy_number": "POL-001",
    "vin": "1HGBH41JXMN109186",
    "vehicle_year": 2021,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "incident_date": "2025-01-15",
    "incident_description": "Rear-ended at stoplight",
    "damage_description": "Rear bumper damage",
    "estimated_damage": 2500.0,
}


def _create_test_claim(repo: ClaimRepository | None = None) -> str:
    """Insert a test claim and return its ID."""
    if repo is None:
        repo = ClaimRepository()
    return repo.create_claim(ClaimInput.model_validate(_SAMPLE_CLAIM))


def _record_job_for_real_claim(job_id: str) -> str:
    """Create a real claim, record a job mapping, and return the claim_id."""
    claim_id = _create_test_claim()
    _record_job_claim_mapping(job_id, claim_id)
    return claim_id


# ---------------------------------------------------------------------------
# is_queue_available
# ---------------------------------------------------------------------------


class TestIsQueueAvailable:
    def test_returns_false_when_no_redis_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert is_queue_available() is False

    def test_returns_false_when_redis_url_empty(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "")
        assert is_queue_available() is False

    def test_returns_false_when_redis_unreachable(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:19999/0")
        assert is_queue_available() is False

    def test_returns_true_when_redis_reachable(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        mock_redis = MagicMock()
        mock_redis.ping.return_value = True
        with patch("redis.Redis.from_url", return_value=mock_redis):
            result = is_queue_available()
        assert result is True
        mock_redis.ping.assert_called_once()


# ---------------------------------------------------------------------------
# _record_job_claim_mapping / _update_job_status / get_job_id_for_claim
# ---------------------------------------------------------------------------


class TestJobDatabaseHelpers:
    def test_record_and_lookup_job_claim_mapping(self):
        """Store a job→claim mapping and retrieve it."""
        claim_id = _record_job_for_real_claim("job-abc")
        assert get_job_id_for_claim(claim_id) == "job-abc"

    def test_get_job_id_for_unknown_claim_returns_none(self):
        assert get_job_id_for_claim("CLM-NOPE") is None

    def test_update_job_status(self):
        """Updating status persists to the DB."""
        _record_job_for_real_claim("job-xyz")
        _update_job_status("job-xyz", "running")

        with get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM claim_jobs WHERE job_id = ?", ("job-xyz",)
            ).fetchone()
        assert row["status"] == "running"

    def test_update_job_status_with_summary(self):
        """Result summary is persisted when provided."""
        _record_job_for_real_claim("job-sum")
        _update_job_status("job-sum", "completed", result_summary="All good")

        with get_connection() as conn:
            row = conn.execute(
                "SELECT status, result_summary FROM claim_jobs WHERE job_id = ?",
                ("job-sum",),
            ).fetchone()
        assert row["status"] == "completed"
        assert row["result_summary"] == "All good"


# ---------------------------------------------------------------------------
# get_job_status (without Redis)
# ---------------------------------------------------------------------------


class TestGetJobStatusNoRedis:
    def test_returns_none_for_unknown_job_when_no_queue(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert get_job_status("nonexistent-job") is None

    def test_returns_db_status_when_queue_unavailable(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        claim_id = _record_job_for_real_claim("job-dbonly")
        _update_job_status("job-dbonly", "running")

        result = get_job_status("job-dbonly")
        assert result is not None
        assert result["job_id"] == "job-dbonly"
        assert result["claim_id"] == claim_id
        assert result["status"] == "running"
        assert "Queue not available" in result.get("message", "")


# ---------------------------------------------------------------------------
# get_job_status (with mocked Redis / RQ)
# ---------------------------------------------------------------------------


def _make_mock_rq_job(*, is_finished=False, is_failed=False, is_queued=False,
                      is_started=False, is_deferred=False, exc_info=None, result=None):
    """Create a mock RQ Job with the given flags."""
    job = MagicMock()
    job.is_finished = is_finished
    job.is_failed = is_failed
    job.is_queued = is_queued
    job.is_started = is_started
    job.is_deferred = is_deferred
    job.exc_info = exc_info
    job.result = result
    # Simulate JobStatus enum returned by get_status() in RQ >= 1.16
    rq_status = MagicMock()
    rq_status.value = "queued"
    job.get_status.return_value = rq_status
    job.meta = {}
    return job


class TestGetJobStatusWithRedis:
    """Test get_job_status when Redis/RQ is mocked."""

    def _get_status_with_mock(self, monkeypatch, job_id: str, mock_job):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        mock_redis = MagicMock()
        mock_queue = MagicMock()
        mock_queue.connection = mock_redis

        with patch("redis.Redis.from_url", return_value=mock_redis), \
             patch("rq.Queue", return_value=mock_queue), \
             patch("rq.job.Job.fetch", return_value=mock_job):
            return get_job_status(job_id)

    def test_status_enum_value_is_serialized_as_string(self, monkeypatch):
        """RQ JobStatus enum must be converted to a plain string."""
        claim_id = _record_job_for_real_claim("job-enum")
        job = _make_mock_rq_job(is_queued=True)

        result = self._get_status_with_mock(monkeypatch, "job-enum", job)

        assert result is not None
        # The status must be a plain str (not a MagicMock / enum)
        assert isinstance(result["status"], str)

    def test_finished_job_returns_completed_status(self, monkeypatch):
        claim_id = _record_job_for_real_claim("job-done")
        job = _make_mock_rq_job(is_finished=True, result={"summary": "ok"})

        result = self._get_status_with_mock(monkeypatch, "job-done", job)

        assert result["status"] == "completed"
        assert result["result"] == {"summary": "ok"}

    def test_failed_job_returns_failed_status(self, monkeypatch):
        claim_id = _record_job_for_real_claim("job-fail")
        job = _make_mock_rq_job(is_failed=True, exc_info="Something went wrong")

        result = self._get_status_with_mock(monkeypatch, "job-fail", job)

        assert result["status"] == "failed"
        assert "error" in result

    def test_queued_job_returns_pending_status(self, monkeypatch):
        claim_id = _record_job_for_real_claim("job-queued")
        job = _make_mock_rq_job(is_queued=True)

        result = self._get_status_with_mock(monkeypatch, "job-queued", job)

        assert result["status"] == "pending"

    def test_started_job_returns_running_status(self, monkeypatch):
        claim_id = _record_job_for_real_claim("job-started")
        job = _make_mock_rq_job(is_started=True)

        result = self._get_status_with_mock(monkeypatch, "job-started", job)

        assert result["status"] == "running"


# ---------------------------------------------------------------------------
# process_claim_task
# ---------------------------------------------------------------------------


class TestProcessClaimTask:
    def test_raises_value_error_when_claim_not_found(self):
        """Non-existent claim_id must raise ValueError so RQ marks job as failed."""
        from claim_agent.queue.tasks import process_claim_task

        with pytest.raises(ValueError, match="Claim not found"):
            process_claim_task(_SAMPLE_CLAIM, "CLM-NONEXISTENT")

    def test_raises_value_error_and_updates_job_status(self):
        """When claim is not found and a job record exists, status is updated to 'failed'."""
        from claim_agent.queue.tasks import process_claim_task

        # Insert a fake claim_id into claim_jobs without a real claim (bypass FK for this test)
        # We need a real claim for the FK, but then use a different claim_id in process_claim_task
        real_claim_id = _create_test_claim()
        _record_job_claim_mapping("job-nf", real_claim_id)

        nonexistent_id = "CLM-NOTFOUND-999"
        with patch("claim_agent.queue.tasks._get_current_job_id", return_value="job-nf"):
            with pytest.raises(ValueError, match="Claim not found"):
                process_claim_task(_SAMPLE_CLAIM, nonexistent_id)

        with get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM claim_jobs WHERE job_id = ?", ("job-nf",)
            ).fetchone()
        assert row["status"] == "failed"

    def test_processes_claim_successfully(self):
        """Successful workflow updates job status to 'completed'."""
        from claim_agent.queue.tasks import process_claim_task

        claim_id = _create_test_claim()
        _record_job_claim_mapping("job-ok", claim_id)

        mock_result = {"claim_id": claim_id, "summary": "All clear", "claim_type": "new"}

        with patch("claim_agent.queue.tasks._get_current_job_id", return_value="job-ok"), \
             patch("claim_agent.queue.tasks.run_claim_workflow", return_value=mock_result):
            result = process_claim_task(_SAMPLE_CLAIM, claim_id)

        assert result == mock_result

        with get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM claim_jobs WHERE job_id = ?", ("job-ok",)
            ).fetchone()
        assert row["status"] == "completed"

    def test_workflow_exception_updates_job_status_to_failed(self):
        """Unhandled exception in workflow marks job as 'failed'."""
        from claim_agent.queue.tasks import process_claim_task

        claim_id = _create_test_claim()
        _record_job_claim_mapping("job-err", claim_id)

        with patch("claim_agent.queue.tasks._get_current_job_id", return_value="job-err"), \
             patch("claim_agent.queue.tasks.run_claim_workflow",
                   side_effect=RuntimeError("LLM failure")):
            with pytest.raises(RuntimeError, match="LLM failure"):
                process_claim_task(_SAMPLE_CLAIM, claim_id)

        with get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM claim_jobs WHERE job_id = ?", ("job-err",)
            ).fetchone()
        assert row["status"] == "failed"

