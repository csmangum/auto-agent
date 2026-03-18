"""PostgreSQL integration tests.

Runs when DATABASE_URL is set (e.g. in CI with postgres service).
Verifies repository CRUD and API work against PostgreSQL.
"""

import os
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
    import subprocess
    result = subprocess.run(
        [__import__("sys").executable, "-m", "alembic", "upgrade", "head"],
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


def test_postgres_repository_crud(postgres_db):
    """Verify ClaimRepository CRUD works against PostgreSQL."""
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

    # Verify audit log
    from sqlalchemy import text

    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT id, action FROM claim_audit_log WHERE claim_id = :cid"),
            {"cid": claim_id},
        ).fetchall()
    assert len(rows) >= 1
