"""Tests for the concurrent claim processing guard (acquire_processing_lock)."""

import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.db.database import init_db
from claim_agent.db import repository as repository_module
from claim_agent.db.repository import ClaimRepository
from claim_agent.db.constants import STATUS_PENDING, STATUS_PROCESSING, STATUS_OPEN, STATUS_FAILED, STATUS_ARCHIVED
from claim_agent.exceptions import (
    ClaimAlreadyProcessingError,
    ClaimNotFoundError,
    InvalidClaimTransitionError,
)
from claim_agent.models.claim import ClaimInput


@pytest.fixture
def temp_db():
    """Temp SQLite DB with schema initialised, CLAIMS_DB_PATH set."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    prev = os.environ.get("CLAIMS_DB_PATH")
    os.environ["CLAIMS_DB_PATH"] = path
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


@pytest.fixture
def repo(temp_db):
    return ClaimRepository(db_path=temp_db)


@pytest.fixture
def claim_id(repo):
    inp = ClaimInput(
        policy_number="POL-GUARD-01",
        vin="1HGBH41JXMN109001",
        vehicle_year=2022,
        vehicle_make="Toyota",
        vehicle_model="Camry",
        incident_date=date(2025, 3, 1),
        incident_description="Minor fender bender",
        damage_description="Front bumper scratched",
    )
    return repo.create_claim(inp)


class TestAcquireProcessingLock:
    """Unit tests for ClaimRepository.acquire_processing_lock."""

    def test_acquires_lock_on_pending_claim(self, repo, claim_id):
        """acquire_processing_lock transitions a pending claim to processing."""
        claim = repo.get_claim(claim_id)
        assert claim["status"] == STATUS_PENDING

        repo.acquire_processing_lock(claim_id)

        claim = repo.get_claim(claim_id)
        assert claim["status"] == STATUS_PROCESSING

    def test_raises_for_unknown_claim(self, repo):
        """acquire_processing_lock raises ClaimNotFoundError for a missing claim."""
        with pytest.raises(ClaimNotFoundError):
            repo.acquire_processing_lock("CLM-DOES-NOT-EXIST")

    def test_raises_when_already_processing(self, repo, claim_id):
        """acquire_processing_lock raises ClaimAlreadyProcessingError when the claim
        is already in processing status."""
        repo.acquire_processing_lock(claim_id)

        with pytest.raises(ClaimAlreadyProcessingError) as exc_info:
            repo.acquire_processing_lock(claim_id)

        assert claim_id in str(exc_info.value)

    def test_claim_already_processing_error_carries_claim_id(self, repo, claim_id):
        """ClaimAlreadyProcessingError.claim_id is set correctly."""
        repo.acquire_processing_lock(claim_id)

        with pytest.raises(ClaimAlreadyProcessingError) as exc_info:
            repo.acquire_processing_lock(claim_id)

        assert exc_info.value.claim_id == claim_id

    def test_audit_log_written_on_success(self, repo, claim_id):
        """A status-change audit entry is written when the lock is acquired."""
        repo.acquire_processing_lock(claim_id)

        events, _ = repo.get_claim_history(claim_id)
        processing_entries = [
            e for e in events
            if e.get("action") == "status_change" and e.get("new_status") == STATUS_PROCESSING
        ]
        assert len(processing_entries) >= 1
        entry = processing_entries[-1]
        assert entry["old_status"] == STATUS_PENDING

    def test_disallows_invalid_transition(self, repo, claim_id):
        """acquire_processing_lock raises InvalidClaimTransitionError when the state
        machine forbids moving from the current status to processing."""
        # Manually drive claim to a terminal state (closed needs payout, so use failed)
        repo.update_claim_status(
            claim_id, STATUS_PROCESSING, actor_id="test", skip_validation=True
        )
        repo.update_claim_status(
            claim_id, STATUS_FAILED, actor_id="test", skip_validation=True
        )
        # STATUS_FAILED -> STATUS_PROCESSING is valid, so use STATUS_ARCHIVED which has
        # no path to processing in the state machine.
        repo.update_claim_status(
            claim_id, STATUS_ARCHIVED, actor_id="test", skip_validation=True
        )

        with pytest.raises(InvalidClaimTransitionError):
            repo.acquire_processing_lock(claim_id)

    def test_allows_reprocessing_from_open(self, repo, claim_id):
        """acquire_processing_lock permits open -> processing (reprocess flow)."""
        repo.update_claim_status(
            claim_id, STATUS_PROCESSING, actor_id="test", skip_validation=True
        )
        repo.update_claim_status(
            claim_id, STATUS_OPEN, actor_id="test", skip_validation=True
        )

        repo.acquire_processing_lock(claim_id)

        claim = repo.get_claim(claim_id)
        assert claim["status"] == STATUS_PROCESSING

    def test_concurrent_lock_only_one_winner(self, repo, claim_id):
        """When two threads simultaneously attempt to acquire the lock, exactly one
        succeeds and the other raises ClaimAlreadyProcessingError."""
        results = []
        errors = []
        barrier = threading.Barrier(2)

        def try_acquire():
            barrier.wait()  # Synchronise both threads to attempt concurrent lock acquisition
            try:
                repo.acquire_processing_lock(claim_id)
                results.append("acquired")
            except ClaimAlreadyProcessingError:
                errors.append("already_processing")
            except Exception as e:
                errors.append(f"unexpected: {e}")

        t1 = threading.Thread(target=try_acquire)
        t2 = threading.Thread(target=try_acquire)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Exactly one thread should have acquired the lock
        assert len(results) == 1, f"Expected 1 winner, got: results={results}, errors={errors}"
        assert results == ["acquired"]
        assert len(errors) == 1
        assert errors == ["already_processing"]

        # Claim status must be processing
        claim = repo.get_claim(claim_id)
        assert claim["status"] == STATUS_PROCESSING

    def test_optimistic_lock_lost_to_non_processing_raises_invalid_transition(
        self, repo, claim_id
    ):
        """If UPDATE affects 0 rows and re-read is not processing, raise InvalidClaimTransitionError."""
        orig_get_connection = repository_module.get_connection
        select_n = [0]

        @contextmanager
        def patched_get_connection(path=None):
            with orig_get_connection(path) as conn:
                real_execute = conn.execute

                def execute_replace(statement, parameters=None, **kwargs):
                    sql_u = str(statement).upper().replace("\n", " ")
                    if "SELECT STATUS FROM CLAIMS" in sql_u:
                        select_n[0] += 1
                        if select_n[0] == 1:
                            return real_execute(statement, parameters, **kwargs)
                        out = MagicMock()
                        out.fetchone.return_value = ("open",)
                        return out
                    if "UPDATE CLAIMS SET STATUS" in sql_u and "UPDATED_AT" in sql_u:
                        zero = MagicMock()
                        zero.rowcount = 0
                        return zero
                    return real_execute(statement, parameters, **kwargs)

                conn.execute = execute_replace
                try:
                    yield conn
                finally:
                    conn.execute = real_execute

        with patch.object(repository_module, "get_connection", patched_get_connection):
            with pytest.raises(InvalidClaimTransitionError, match="concurrently"):
                repo.acquire_processing_lock(claim_id)
