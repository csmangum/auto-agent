"""PostgreSQL integration tests for portal token inactivity enforcement.

Mirrors the key inactivity / ``last_used_at`` boundary cases from
``tests/test_portal_token_inactivity.py`` (SQLite) and runs them against a
real PostgreSQL database.  Tests are skipped automatically when ``DATABASE_URL``
is not set (or does not reference PostgreSQL).

Marker: ``integration``  – run with::

    pytest tests/integration/test_postgres_portal_token_inactivity.py -v -m integration

"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Module-level skip / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def postgres_url():
    """DATABASE_URL from environment. Skip tests if not set or not PostgreSQL."""
    url = os.environ.get("DATABASE_URL")
    if not url or "postgresql" not in url:
        pytest.skip("DATABASE_URL (PostgreSQL) not set – skipping PostgreSQL portal-token tests")
    return url


@pytest.fixture(autouse=True)
def _use_postgres(postgres_url):
    """Ensure DATABASE_URL is set and engine cache is reset for each test."""
    from claim_agent.db.database import reset_engine_cache

    prev = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = postgres_url
    reset_engine_cache()
    yield
    reset_engine_cache()
    if prev is not None:
        os.environ["DATABASE_URL"] = prev
    elif "DATABASE_URL" in os.environ:
        del os.environ["DATABASE_URL"]


@pytest.fixture(scope="module")
def _run_migrations(postgres_url):
    """Run ``alembic upgrade head`` once per module to prepare the schema."""
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": postgres_url},
    )
    if result.returncode != 0:
        pytest.fail(f"alembic upgrade failed:\n{result.stderr}")


@pytest.fixture()
def pg_seeded(postgres_url, _run_migrations):
    """Reset portal token tables and insert a test claim, then yield the DB URL.

    Cleaning only the four portal token tables (not the whole schema) keeps the
    fixture fast while guaranteeing each test starts from a known state.
    """
    from claim_agent.db.database import get_connection

    claim_id = "CLM-PGTEST001"
    with get_connection() as conn:
        # Clear token tables so each test gets a clean slate.
        for table in (
            "claim_access_tokens",
            "repair_shop_access_tokens",
            "third_party_access_tokens",
            "external_portal_tokens",
        ):
            conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608

        # Ensure the test claim exists (upsert-style to survive concurrent test runs).
        conn.execute(
            text("""
                INSERT INTO claims (
                    id, policy_number, vin, vehicle_year, vehicle_make,
                    vehicle_model, incident_date, incident_description,
                    damage_description, estimated_damage, claim_type, status
                ) VALUES (
                    :id, :policy_number, :vin, :vehicle_year, :vehicle_make,
                    :vehicle_model, :incident_date, :incident_description,
                    :damage_description, :estimated_damage, :claim_type, :status
                ) ON CONFLICT (id) DO NOTHING
            """),
            {
                "id": claim_id,
                "policy_number": "POL-PGTEST",
                "vin": "VINPGTEST0001",
                "vehicle_year": 2022,
                "vehicle_make": "Test",
                "vehicle_model": "Postgres",
                "incident_date": "2025-01-15",
                "incident_description": "PostgreSQL portal token test",
                "damage_description": "Minor",
                "estimated_damage": 1000.0,
                "claim_type": "new",
                "status": "open",
            },
        )
    yield claim_id


# ---------------------------------------------------------------------------
# PostgreSQL-compatible helpers (use SQLAlchemy, not sqlite3)
# ---------------------------------------------------------------------------


def _pg_set_last_used(table: str, days_ago: float) -> None:
    """Set ``last_used_at`` to *days_ago* days before now via SQLAlchemy."""
    from claim_agent.db.database import get_connection

    ts = datetime.now(timezone.utc) - timedelta(days=days_ago)
    with get_connection() as conn:
        conn.execute(
            text(f"UPDATE {table} SET last_used_at = :ts"),  # noqa: S608
            {"ts": ts},
        )


def _pg_set_last_used_raw(table: str, value: str) -> None:
    """Set ``last_used_at`` to an arbitrary string (for malformed-value tests)."""
    from claim_agent.db.database import get_connection

    with get_connection() as conn:
        conn.execute(
            text(f"UPDATE {table} SET last_used_at = :v"),  # noqa: S608
            {"v": value},
        )


def _pg_get_last_used(table: str) -> datetime | None:
    """Fetch ``last_used_at`` from *table* (expects a single row)."""
    from claim_agent.db.database import get_connection

    with get_connection() as conn:
        row = conn.execute(
            text(f"SELECT last_used_at FROM {table}")  # noqa: S608
        ).fetchone()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# Portal env fixture (enable all portals, short inactivity timeout)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_portals(monkeypatch):
    """Enable all portals with a 3-day inactivity timeout."""
    monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "true")
    monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "token")
    monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "true")
    monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
    monkeypatch.setenv("CLAIM_PORTAL_INACTIVITY_TIMEOUT_DAYS", "3")
    monkeypatch.setenv("REPAIR_SHOP_PORTAL_INACTIVITY_TIMEOUT_DAYS", "3")
    monkeypatch.setenv("THIRD_PARTY_PORTAL_INACTIVITY_TIMEOUT_DAYS", "3")
    from claim_agent.config import reload_settings

    reload_settings()
    yield
    reload_settings()


# ===========================================================================
# Claimant portal – verify_claimant_access
# ===========================================================================


class TestPGClaimantVerifyAccess:
    """Inactivity enforcement for ``verify_claimant_access`` on PostgreSQL."""

    def test_fresh_token_null_last_used_accepted(self, pg_seeded):
        """NULL last_used_at → accepted (new token has no inactivity evidence)."""
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            verify_claimant_access,
        )

        raw = create_claim_access_token(pg_seeded)
        result = verify_claimant_access(pg_seeded, token=raw)
        assert result is not None
        assert result.claim_id == pg_seeded

    def test_recently_used_token_accepted(self, pg_seeded):
        """last_used_at 1 day ago (within 3-day window) → accepted."""
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            verify_claimant_access,
        )

        raw = create_claim_access_token(pg_seeded)
        _pg_set_last_used("claim_access_tokens", days_ago=1)
        result = verify_claimant_access(pg_seeded, token=raw)
        assert result is not None

    def test_inactive_token_rejected(self, pg_seeded):
        """last_used_at 5 days ago (beyond 3-day window) → rejected."""
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            verify_claimant_access,
        )

        raw = create_claim_access_token(pg_seeded)
        _pg_set_last_used("claim_access_tokens", days_ago=5)
        result = verify_claimant_access(pg_seeded, token=raw)
        assert result is None

    def test_boundary_one_second_before_cutoff_rejected(self, pg_seeded):
        """last_used_at 1 s before the cutoff → rejected (strict <)."""
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            verify_claimant_access,
        )
        from claim_agent.db.database import get_connection

        raw = create_claim_access_token(pg_seeded)
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        stale = cutoff - timedelta(seconds=1)
        with get_connection() as conn:
            conn.execute(
                text("UPDATE claim_access_tokens SET last_used_at = :ts"),
                {"ts": stale},
            )
        result = verify_claimant_access(pg_seeded, token=raw)
        assert result is None

    def test_boundary_one_second_after_cutoff_accepted(self, pg_seeded):
        """last_used_at 1 s after the cutoff → accepted."""
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            verify_claimant_access,
        )
        from claim_agent.db.database import get_connection

        raw = create_claim_access_token(pg_seeded)
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        fresh = cutoff + timedelta(seconds=1)
        with get_connection() as conn:
            conn.execute(
                text("UPDATE claim_access_tokens SET last_used_at = :ts"),
                {"ts": fresh},
            )
        result = verify_claimant_access(pg_seeded, token=raw)
        assert result is not None

    def test_last_used_at_updated_on_success(self, pg_seeded):
        """Successful verification updates ``last_used_at`` in PostgreSQL."""
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            verify_claimant_access,
        )

        raw = create_claim_access_token(pg_seeded)
        before = _pg_get_last_used("claim_access_tokens")
        assert before is None
        verify_claimant_access(pg_seeded, token=raw)
        after = _pg_get_last_used("claim_access_tokens")
        assert after is not None

    def test_rejected_inactive_token_does_not_update_last_used(self, pg_seeded):
        """Failed (inactive) verification must not update ``last_used_at``."""
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            verify_claimant_access,
        )

        raw = create_claim_access_token(pg_seeded)
        _pg_set_last_used("claim_access_tokens", days_ago=5)
        before = _pg_get_last_used("claim_access_tokens")
        assert verify_claimant_access(pg_seeded, token=raw) is None
        after = _pg_get_last_used("claim_access_tokens")
        # Timestamps should be equal (same object or same value)
        assert after == before


# ===========================================================================
# Claimant portal – get_claim_ids_for_claimant
# ===========================================================================


class TestPGClaimantGetClaimIds:
    """Inactivity enforcement for ``get_claim_ids_for_claimant`` on PostgreSQL."""

    def test_fresh_token_returns_claims(self, pg_seeded):
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            get_claim_ids_for_claimant,
        )

        raw = create_claim_access_token(pg_seeded)
        ids = get_claim_ids_for_claimant(token=raw)
        assert pg_seeded in ids

    def test_recently_used_token_returns_claims(self, pg_seeded):
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            get_claim_ids_for_claimant,
        )

        raw = create_claim_access_token(pg_seeded)
        _pg_set_last_used("claim_access_tokens", days_ago=1)
        ids = get_claim_ids_for_claimant(token=raw)
        assert pg_seeded in ids

    def test_inactive_token_excluded(self, pg_seeded):
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            get_claim_ids_for_claimant,
        )

        raw = create_claim_access_token(pg_seeded)
        _pg_set_last_used("claim_access_tokens", days_ago=10)
        ids = get_claim_ids_for_claimant(token=raw)
        assert ids == []

    def test_last_used_at_updated(self, pg_seeded):
        from claim_agent.services.portal_verification import (
            create_claim_access_token,
            get_claim_ids_for_claimant,
        )

        raw = create_claim_access_token(pg_seeded)
        assert _pg_get_last_used("claim_access_tokens") is None
        get_claim_ids_for_claimant(token=raw)
        assert _pg_get_last_used("claim_access_tokens") is not None


# ===========================================================================
# Repair shop portal – verify_repair_shop_token
# ===========================================================================


class TestPGRepairShopInactivity:
    """Inactivity enforcement for ``verify_repair_shop_token`` on PostgreSQL."""

    def test_fresh_token_accepted(self, pg_seeded):
        from claim_agent.services.repair_shop_portal_tokens import (
            create_repair_shop_access_token,
            verify_repair_shop_token,
        )

        raw = create_repair_shop_access_token(pg_seeded)
        result = verify_repair_shop_token(pg_seeded, raw)
        assert result is not None
        assert result.claim_id == pg_seeded

    def test_recently_used_token_accepted(self, pg_seeded):
        from claim_agent.services.repair_shop_portal_tokens import (
            create_repair_shop_access_token,
            verify_repair_shop_token,
        )

        raw = create_repair_shop_access_token(pg_seeded)
        _pg_set_last_used("repair_shop_access_tokens", days_ago=2)
        result = verify_repair_shop_token(pg_seeded, raw)
        assert result is not None

    def test_inactive_token_rejected(self, pg_seeded):
        from claim_agent.services.repair_shop_portal_tokens import (
            create_repair_shop_access_token,
            verify_repair_shop_token,
        )

        raw = create_repair_shop_access_token(pg_seeded)
        _pg_set_last_used("repair_shop_access_tokens", days_ago=7)
        result = verify_repair_shop_token(pg_seeded, raw)
        assert result is None

    def test_last_used_at_updated_on_success(self, pg_seeded):
        from claim_agent.services.repair_shop_portal_tokens import (
            create_repair_shop_access_token,
            verify_repair_shop_token,
        )

        raw = create_repair_shop_access_token(pg_seeded)
        assert _pg_get_last_used("repair_shop_access_tokens") is None
        verify_repair_shop_token(pg_seeded, raw)
        assert _pg_get_last_used("repair_shop_access_tokens") is not None

    def test_rejected_inactive_does_not_update_last_used(self, pg_seeded):
        from claim_agent.services.repair_shop_portal_tokens import (
            create_repair_shop_access_token,
            verify_repair_shop_token,
        )

        raw = create_repair_shop_access_token(pg_seeded)
        _pg_set_last_used("repair_shop_access_tokens", days_ago=7)
        before = _pg_get_last_used("repair_shop_access_tokens")
        assert verify_repair_shop_token(pg_seeded, raw) is None
        assert _pg_get_last_used("repair_shop_access_tokens") == before


# ===========================================================================
# Third-party portal – verify_third_party_token
# ===========================================================================


class TestPGThirdPartyInactivity:
    """Inactivity enforcement for ``verify_third_party_token`` on PostgreSQL."""

    def test_fresh_token_accepted(self, pg_seeded):
        from claim_agent.services.third_party_portal_tokens import (
            create_third_party_access_token,
            verify_third_party_token,
        )

        raw = create_third_party_access_token(pg_seeded)
        result = verify_third_party_token(pg_seeded, raw)
        assert result is not None
        assert result.claim_id == pg_seeded

    def test_recently_used_token_accepted(self, pg_seeded):
        from claim_agent.services.third_party_portal_tokens import (
            create_third_party_access_token,
            verify_third_party_token,
        )

        raw = create_third_party_access_token(pg_seeded)
        _pg_set_last_used("third_party_access_tokens", days_ago=1)
        result = verify_third_party_token(pg_seeded, raw)
        assert result is not None

    def test_inactive_token_rejected(self, pg_seeded):
        from claim_agent.services.third_party_portal_tokens import (
            create_third_party_access_token,
            verify_third_party_token,
        )

        raw = create_third_party_access_token(pg_seeded)
        _pg_set_last_used("third_party_access_tokens", days_ago=10)
        result = verify_third_party_token(pg_seeded, raw)
        assert result is None

    def test_last_used_at_updated_on_success(self, pg_seeded):
        from claim_agent.services.third_party_portal_tokens import (
            create_third_party_access_token,
            verify_third_party_token,
        )

        raw = create_third_party_access_token(pg_seeded)
        assert _pg_get_last_used("third_party_access_tokens") is None
        verify_third_party_token(pg_seeded, raw)
        assert _pg_get_last_used("third_party_access_tokens") is not None


# ===========================================================================
# Unified portal – verify_unified_portal_token
# ===========================================================================


class TestPGUnifiedPortalInactivity:
    """Inactivity enforcement for ``verify_unified_portal_token`` on PostgreSQL."""

    def test_fresh_claimant_token_accepted(self, pg_seeded):
        from claim_agent.services.unified_portal_tokens import (
            create_unified_portal_token,
            verify_unified_portal_token,
        )

        raw = create_unified_portal_token(
            "claimant", scopes=["read_claim"], claim_id=pg_seeded
        )
        result = verify_unified_portal_token(raw)
        assert result is not None
        assert result.role == "claimant"

    def test_recently_used_token_accepted(self, pg_seeded):
        from claim_agent.services.unified_portal_tokens import (
            create_unified_portal_token,
            verify_unified_portal_token,
        )

        raw = create_unified_portal_token(
            "claimant", scopes=["read_claim"], claim_id=pg_seeded
        )
        _pg_set_last_used("external_portal_tokens", days_ago=1)
        result = verify_unified_portal_token(raw)
        assert result is not None

    def test_inactive_claimant_token_rejected(self, pg_seeded):
        from claim_agent.services.unified_portal_tokens import (
            create_unified_portal_token,
            verify_unified_portal_token,
        )

        raw = create_unified_portal_token(
            "claimant", scopes=["read_claim"], claim_id=pg_seeded
        )
        _pg_set_last_used("external_portal_tokens", days_ago=5)
        result = verify_unified_portal_token(raw)
        assert result is None

    def test_inactive_repair_shop_token_rejected(self, pg_seeded):
        from claim_agent.services.unified_portal_tokens import (
            create_unified_portal_token,
            verify_unified_portal_token,
        )

        raw = create_unified_portal_token(
            "repair_shop",
            scopes=["read_claim"],
            claim_id=pg_seeded,
            shop_id="SHOP-PG1",
        )
        _pg_set_last_used("external_portal_tokens", days_ago=4)
        result = verify_unified_portal_token(raw)
        assert result is None

    def test_inactive_tpa_token_rejected(self, pg_seeded):
        from claim_agent.services.unified_portal_tokens import (
            create_unified_portal_token,
            verify_unified_portal_token,
        )

        raw = create_unified_portal_token(
            "tpa", scopes=["read_claim"], claim_id=pg_seeded
        )
        _pg_set_last_used("external_portal_tokens", days_ago=4)
        result = verify_unified_portal_token(raw)
        assert result is None

    def test_last_used_at_updated_on_success(self, pg_seeded):
        from claim_agent.services.unified_portal_tokens import (
            create_unified_portal_token,
            verify_unified_portal_token,
        )

        raw = create_unified_portal_token(
            "repair_shop",
            scopes=["read_claim", "update_repair_status"],
            claim_id=pg_seeded,
            shop_id="SHOP-PG1",
        )
        assert _pg_get_last_used("external_portal_tokens") is None
        verify_unified_portal_token(raw)
        assert _pg_get_last_used("external_portal_tokens") is not None

    def test_boundary_one_second_before_cutoff_rejected(self, pg_seeded):
        """last_used_at 1 s before the cutoff → rejected on PostgreSQL."""
        from claim_agent.services.unified_portal_tokens import (
            create_unified_portal_token,
            verify_unified_portal_token,
        )
        from claim_agent.db.database import get_connection

        raw = create_unified_portal_token(
            "claimant", scopes=["read_claim"], claim_id=pg_seeded
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        stale = cutoff - timedelta(seconds=1)
        with get_connection() as conn:
            conn.execute(
                text("UPDATE external_portal_tokens SET last_used_at = :ts"),
                {"ts": stale},
            )
        result = verify_unified_portal_token(raw)
        assert result is None

    def test_boundary_one_second_after_cutoff_accepted(self, pg_seeded):
        """last_used_at 1 s after the cutoff → accepted on PostgreSQL."""
        from claim_agent.services.unified_portal_tokens import (
            create_unified_portal_token,
            verify_unified_portal_token,
        )
        from claim_agent.db.database import get_connection

        raw = create_unified_portal_token(
            "claimant", scopes=["read_claim"], claim_id=pg_seeded
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        fresh = cutoff + timedelta(seconds=1)
        with get_connection() as conn:
            conn.execute(
                text("UPDATE external_portal_tokens SET last_used_at = :ts"),
                {"ts": fresh},
            )
        result = verify_unified_portal_token(raw)
        assert result is not None


# ===========================================================================
# Malformed last_used_at (fail-closed) on PostgreSQL
# ===========================================================================


class TestPGMalformedLastUsedAt:
    """PostgreSQL stores TIMESTAMPTZ natively; malformed string inserts should fail closed."""

    def test_claimant_verify_rejects_unparseable(self, pg_seeded):
        """Verify that the service rejects when last_used_at cannot be parsed.

        PostgreSQL TIMESTAMPTZ will reject a plainly invalid string at the DB
        level, but the service layer must also handle any value that passes
        through as text (e.g. a TEXT cast).  We test via the shared helper
        ``portal_token_last_used_rejects`` which all four services delegate to.
        """
        from claim_agent.services.portal_token_utils import portal_token_last_used_rejects
        import logging

        logger = logging.getLogger("test")
        inactivity_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        assert portal_token_last_used_rejects(
            "not-a-date",
            inactivity_cutoff,
            logger=logger,
            inactive_log=None,
        ) is True

    def test_repair_shop_rejects_unparseable(self, pg_seeded):
        from claim_agent.services.portal_token_utils import portal_token_last_used_rejects
        import logging

        logger = logging.getLogger("test")
        inactivity_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        assert portal_token_last_used_rejects(
            "bogus-timestamp",
            inactivity_cutoff,
            logger=logger,
            inactive_log=None,
        ) is True

    def test_third_party_rejects_unparseable(self, pg_seeded):
        from claim_agent.services.portal_token_utils import portal_token_last_used_rejects
        import logging

        logger = logging.getLogger("test")
        inactivity_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        assert portal_token_last_used_rejects(
            "x",
            inactivity_cutoff,
            logger=logger,
            inactive_log=None,
        ) is True

    def test_unified_rejects_unparseable(self, pg_seeded):
        from claim_agent.services.portal_token_utils import portal_token_last_used_rejects
        import logging

        logger = logging.getLogger("test")
        inactivity_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        assert portal_token_last_used_rejects(
            "nope",
            inactivity_cutoff,
            logger=logger,
            inactive_log=None,
        ) is True

    def test_null_last_used_never_rejects(self, pg_seeded):
        """NULL last_used_at (None) must never trigger the inactivity check."""
        from claim_agent.services.portal_token_utils import portal_token_last_used_rejects
        import logging

        logger = logging.getLogger("test")
        inactivity_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        assert portal_token_last_used_rejects(
            None,
            inactivity_cutoff,
            logger=logger,
            inactive_log=None,
        ) is False

    def test_timezone_aware_timestamp_from_postgres(self, pg_seeded):
        """last_used_at returned by PostgreSQL as a timezone-aware datetime is handled."""
        from claim_agent.services.portal_token_utils import portal_token_last_used_rejects
        import logging

        logger = logging.getLogger("test")
        # Simulate a timezone-aware datetime object (what PostgreSQL returns)
        inactivity_cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        recent = datetime.now(timezone.utc) - timedelta(days=1)
        assert portal_token_last_used_rejects(
            recent,
            inactivity_cutoff,
            logger=logger,
            inactive_log=None,
        ) is False

        stale = datetime.now(timezone.utc) - timedelta(days=5)
        assert portal_token_last_used_rejects(
            stale,
            inactivity_cutoff,
            logger=logger,
            inactive_log=None,
        ) is True
