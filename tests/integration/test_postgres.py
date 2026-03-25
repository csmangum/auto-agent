"""PostgreSQL integration tests.

Runs when DATABASE_URL is set (e.g. in CI with postgres service).
Verifies repository CRUD and API work against PostgreSQL.
"""

import os
import sys
import subprocess
import threading
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def postgres_url():
    """DATABASE_URL from environment. Skip tests if not set."""
    url = os.environ.get("DATABASE_URL")
    if not url or "postgresql" not in url:
        pytest.skip("DATABASE_URL (PostgreSQL) not set")
    return url


@pytest.fixture(autouse=True)
def use_postgres(postgres_url):
    """Ensure DATABASE_URL is set for PostgreSQL tests."""
    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = postgres_url
    yield
    if prev is not None:
        os.environ["DATABASE_URL"] = prev
    elif "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]


@pytest.fixture
def postgres_db(postgres_url):
    """Reset engine cache and run migrations for a fresh PostgreSQL schema."""
    from claim_agent.db.database import reset_engine_cache

    reset_engine_cache()
    # Run migrations
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed: {result.stderr}")
    yield postgres_url
    reset_engine_cache()


def test_postgres_connection(postgres_db):
    """Verify we can connect to PostgreSQL and run a simple query."""
    from sqlalchemy import text

    from claim_agent.db.database import get_connection

    with get_connection() as conn:
        row = conn.execute(text("SELECT 1 as x")).fetchone()
    assert row is not None
    assert row[0] == 1


def test_postgres_version(postgres_db):
    """Verify PostgreSQL version meets minimum requirements (12+)."""
    from sqlalchemy import text

    from claim_agent.db.database import get_connection

    with get_connection() as conn:
        row = conn.execute(text("SHOW server_version_num")).fetchone()
    assert row is not None
    # server_version_num is a zero-padded string like "140006"; 120000 == PostgreSQL 12.0
    version_num = int(row[0])
    assert version_num >= 120000, (
        f"PostgreSQL 12+ required; server_version_num={version_num}"
    )


def test_postgres_repository_crud(postgres_db):
    """Verify ClaimRepository CRUD works against PostgreSQL."""
    from sqlalchemy import text

    from claim_agent.db.database import get_connection
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput

    repo = ClaimRepository()
    claim_input = ClaimInput(
        policy_number="POL-PG001",
        vin="VINPG123",
        vehicle_year=2022,
        vehicle_make="Test",
        vehicle_model="Postgres",
        incident_date="2025-01-15",
        incident_description="PostgreSQL integration test",
        damage_description="Minor",
    )
    claim_id = repo.create_claim(claim_input)
    assert claim_id.startswith("CLM-")

    claim = repo.get_claim(claim_id)
    assert claim is not None
    assert claim["policy_number"] == "POL-PG001"
    assert claim["vin"] == "VINPG123"

    # Verify audit log entry created on insert
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT id, action FROM claim_audit_log WHERE claim_id = :cid"),
            {"cid": claim_id},
        ).fetchall()
    assert len(rows) >= 1

    # Update and re-fetch
    repo.update_claim(claim_id, {"status": "in_review", "assignee": "adjuster-pg-test"})
    updated = repo.get_claim(claim_id)
    assert updated is not None
    assert updated["status"] == "in_review"
    assert updated["assignee"] == "adjuster-pg-test"

    # List claims and confirm our claim appears
    claims = repo.list_claims(limit=200)
    ids = [c["id"] for c in claims]
    assert claim_id in ids


def test_postgres_repository_update_status_transitions(postgres_db):
    """Verify status transitions are persisted correctly on PostgreSQL."""
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput

    repo = ClaimRepository()
    claim_input = ClaimInput(
        policy_number="POL-PG-STATUS",
        vin="VINPGST",
        vehicle_year=2023,
        vehicle_make="Status",
        vehicle_model="Test",
        incident_date="2025-02-01",
        incident_description="Status transition test",
        damage_description="Moderate",
    )
    claim_id = repo.create_claim(claim_input)

    for status in ("in_review", "approved", "closed"):
        repo.update_claim(claim_id, {"status": status})
        claim = repo.get_claim(claim_id)
        assert claim is not None
        assert claim["status"] == status


def test_postgres_concurrent_writes(postgres_db):
    """Verify PostgreSQL handles concurrent writes without locking errors.

    This is the key test that would fail on SQLite with multiple writers.
    """
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput

    errors: list[Exception] = []
    created_ids: list[str] = []
    lock = threading.Lock()

    def insert_claim(worker_id: int) -> None:
        repo = ClaimRepository()
        try:
            cid = repo.create_claim(
                ClaimInput(
                    policy_number=f"POL-CONC-{worker_id:04d}",
                    vin=f"VINCONC{worker_id:05d}",
                    vehicle_year=2024,
                    vehicle_make="Concurrent",
                    vehicle_model="Writer",
                    incident_date="2025-03-01",
                    incident_description=f"Concurrent write test {worker_id}",
                    damage_description="Minor",
                )
            )
            with lock:
                created_ids.append(cid)
        except Exception as exc:
            with lock:
                errors.append(exc)

    num_threads = 10
    threads = [threading.Thread(target=insert_claim, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent writes produced errors: {errors}"
    assert len(created_ids) == num_threads, (
        f"Expected {num_threads} successful inserts, got {len(created_ids)}"
    )


def test_postgres_connection_pooling(postgres_db):
    """Verify multiple sequential connections work correctly (pool reuse)."""
    from sqlalchemy import text

    from claim_agent.db.database import get_connection

    results = []
    for i in range(20):
        with get_connection() as conn:
            row = conn.execute(text("SELECT :i AS n"), {"i": i}).fetchone()
            assert row is not None
            results.append(row[0])
    assert results == list(range(20))


def test_postgres_is_postgres_backend(postgres_db):
    """Verify is_postgres_backend() returns True when DATABASE_URL is set."""
    from claim_agent.db.database import is_postgres_backend

    assert is_postgres_backend() is True


def test_postgres_alembic_migration_idempotent(postgres_db):
    """Running alembic upgrade head twice should be a no-op (idempotent)."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Second alembic upgrade failed: {result.stderr}"


def test_postgres_replica_connection_falls_back_to_primary(postgres_db):
    """get_replica_connection() falls back to primary when replica is not configured."""
    from sqlalchemy import text

    from claim_agent.db.database import get_replica_connection

    with get_replica_connection() as conn:
        row = conn.execute(text("SELECT 1 AS x")).fetchone()
    assert row is not None
    assert row[0] == 1


def test_postgres_graph_phone_sql_matches_python_normalization(postgres_db):
    """sql_expr_phone_normalized_postgres matches normalize_party_phone_for_graph."""
    from sqlalchemy import text

    from claim_agent.db.database import get_connection
    from claim_agent.utils.graph_contact_normalize import (
        normalize_party_phone_for_graph,
        sql_expr_phone_normalized_postgres,
    )

    phones = [
        "+1 (555) 234-5678",
        "(555) 234-5678",
        "555-234-5678",
        "12345678901234",
        "+44 20 7946 0958",
    ]
    expr = sql_expr_phone_normalized_postgres("cp")
    with get_connection() as conn:
        for p in phones:
            row = conn.execute(
                text(f"SELECT {expr} AS n FROM (SELECT :phone AS phone) AS cp"),
                {"phone": p},
            ).fetchone()
            expected = normalize_party_phone_for_graph(p) or ""
            assert row is not None
            assert row[0] == expected, f"phone={p!r} sql={row[0]!r} py={expected!r}"
