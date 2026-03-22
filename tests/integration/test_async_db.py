"""Tests for async database support (asyncpg / SQLAlchemy async engine).

These tests verify:
- ``get_connection_async()`` raises RuntimeError for SQLite (not supported).
- ``_get_async_database_url()`` correctly converts PostgreSQL URLs to asyncpg scheme.
- ``reset_engine_cache()`` disposes the async engine alongside the sync engine.
- The ``get_async_db`` FastAPI dependency is importable and structurally correct.

Full end-to-end async PostgreSQL tests are in ``test_postgres.py`` and only run
when ``DATABASE_URL`` (pointing at a live PostgreSQL instance) is set.
"""

import asyncio
import os

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset():
    """Reset engine caches and clear DATABASE_URL between tests."""
    from claim_agent.config import reload_settings
    from claim_agent.db.database import reset_engine_cache

    reset_engine_cache()
    os.environ.pop("DATABASE_URL", None)
    reload_settings()


# ---------------------------------------------------------------------------
# URL conversion
# ---------------------------------------------------------------------------


class TestGetAsyncDatabaseUrl:
    """Unit tests for _get_async_database_url()."""

    def setup_method(self):
        _reset()

    def teardown_method(self):
        _reset()

    def test_raises_for_sqlite_backend(self):
        """RuntimeError raised when DATABASE_URL is not set (SQLite mode)."""
        from claim_agent.db.database import _get_async_database_url

        with pytest.raises(RuntimeError, match="PostgreSQL"):
            _get_async_database_url()

    def test_converts_postgresql_scheme(self):
        """postgresql:// → postgresql+asyncpg://."""
        os.environ["DATABASE_URL"] = "postgresql://user:pw@localhost/db"
        from claim_agent.config import reload_settings

        reload_settings()
        from claim_agent.db.database import _get_async_database_url

        url = _get_async_database_url()
        assert url.startswith("postgresql+asyncpg://"), url

    def test_converts_postgres_alias(self):
        """postgres:// (legacy alias) → postgresql+asyncpg://."""
        os.environ["DATABASE_URL"] = "postgres://user:pw@localhost/db"
        from claim_agent.config import reload_settings

        reload_settings()
        from claim_agent.db.database import _get_async_database_url

        url = _get_async_database_url()
        assert url.startswith("postgresql+asyncpg://"), url

    def test_passthrough_if_already_asyncpg(self):
        """URL already using asyncpg scheme is returned unchanged."""
        raw = "postgresql+asyncpg://user:pw@localhost/db"
        os.environ["DATABASE_URL"] = raw
        from claim_agent.config import reload_settings

        reload_settings()
        from claim_agent.db.database import _get_async_database_url

        assert _get_async_database_url() == raw


# ---------------------------------------------------------------------------
# get_connection_async() with SQLite (should raise)
# ---------------------------------------------------------------------------


class TestGetConnectionAsyncSqlite:
    """Verify that get_connection_async() is unusable with SQLite."""

    def setup_method(self):
        _reset()

    def teardown_method(self):
        _reset()

    def test_raises_runtime_error_for_sqlite(self):
        """get_connection_async() must raise RuntimeError for the SQLite backend."""
        from claim_agent.db.database import get_connection_async

        async def _run():
            async with get_connection_async():
                pass

        with pytest.raises(RuntimeError, match="PostgreSQL"):
            asyncio.run(_run())


# ---------------------------------------------------------------------------
# reset_engine_cache clears async engine
# ---------------------------------------------------------------------------


class TestResetEngineCacheAsync:
    """Verify that reset_engine_cache() also disposes the async engine."""

    def setup_method(self):
        _reset()

    def teardown_method(self):
        _reset()

    def test_async_engine_cleared_by_reset(self):
        """After reset_engine_cache(), _async_engine is None again."""
        import claim_agent.db.database as db_mod
        from claim_agent.config import reload_settings

        os.environ["DATABASE_URL"] = "postgresql://user:pw@localhost/db"
        reload_settings()

        # Build the async engine (lazy init)
        db_mod._get_async_engine()
        assert db_mod._async_engine is not None

        db_mod.reset_engine_cache()
        assert db_mod._async_engine is None


# ---------------------------------------------------------------------------
# get_async_db FastAPI dependency
# ---------------------------------------------------------------------------


class TestGetAsyncDbDependency:
    """Structural tests for the get_async_db FastAPI dependency."""

    def test_get_async_db_is_importable(self):
        """get_async_db must be importable from claim_agent.api.deps."""
        from claim_agent.api.deps import get_async_db  # noqa: F401

    def test_get_async_db_is_async_generator(self):
        """get_async_db must be an async generator function."""
        import inspect

        from claim_agent.api.deps import get_async_db

        assert inspect.isasyncgenfunction(get_async_db)


# ---------------------------------------------------------------------------
# PostgreSQL end-to-end (skipped unless DATABASE_URL is set)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def postgres_url():
    """DATABASE_URL from environment. Skip if not pointing at PostgreSQL."""
    url = os.environ.get("DATABASE_URL", "")
    if not url or "postgresql" not in url:
        pytest.skip("DATABASE_URL (PostgreSQL) not configured")
    return url


class TestGetConnectionAsyncPostgres:
    """End-to-end async connection tests (require a live PostgreSQL instance)."""

    def test_async_connection_executes_query(self, postgres_url):
        """get_connection_async() can execute a simple query against PostgreSQL."""
        from sqlalchemy import text

        from claim_agent.config import reload_settings
        from claim_agent.db.database import get_connection_async, reset_engine_cache

        reset_engine_cache()
        os.environ["DATABASE_URL"] = postgres_url
        reload_settings()

        async def _run():
            async with get_connection_async() as conn:
                result = await conn.execute(text("SELECT 1 AS x"))
                row = result.fetchone()
            return row

        row = asyncio.run(_run())
        assert row is not None
        assert row[0] == 1
        reset_engine_cache()

    def test_async_connection_rollback_on_error(self, postgres_url):
        """Errors inside get_connection_async() trigger a rollback."""
        from sqlalchemy import text

        from claim_agent.config import reload_settings
        from claim_agent.db.database import get_connection_async, reset_engine_cache

        reset_engine_cache()
        os.environ["DATABASE_URL"] = postgres_url
        reload_settings()

        async def _run():
            async with get_connection_async() as conn:
                await conn.execute(text("SELECT 1"))
                raise ValueError("simulated error")

        with pytest.raises(ValueError, match="simulated error"):
            asyncio.run(_run())

        reset_engine_cache()

    def test_async_exit_preserves_sync_and_replica_engine_cache(self, postgres_url):
        """Regression: exiting get_connection_async must not clear global sync/replica engines."""
        from sqlalchemy import text

        from claim_agent.config import reload_settings

        import claim_agent.db.database as db_mod

        db_mod.reset_engine_cache()
        os.environ["DATABASE_URL"] = postgres_url
        os.environ["READ_REPLICA_DATABASE_URL"] = postgres_url
        reload_settings()

        sync_before = db_mod._get_engine()
        replica_before = db_mod._get_replica_engine()
        assert sync_before is not None
        assert replica_before is not None
        assert sync_before is not replica_before

        async def _run():
            async with db_mod.get_connection_async() as conn:
                await conn.execute(text("SELECT 1"))

        asyncio.run(_run())

        assert db_mod._engine is sync_before
        assert db_mod._replica_engine is replica_before

        os.environ.pop("READ_REPLICA_DATABASE_URL", None)
        db_mod.reset_engine_cache()
