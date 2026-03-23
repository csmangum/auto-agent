"""Parity tests: shared SQLite DDL constants vs. corresponding PostgreSQL migration DDL.

Verifies that the column names defined in ``schema_auth_sqlite.py`` and
``schema_privacy_sqlite.py`` stay aligned with the PostgreSQL equivalents in the
corresponding Alembic revisions (046, 047, 048).

Uses the same helpers as ``test_schema_incidents_parity.py``.
"""

from pathlib import Path

import claim_agent.db.schema_auth_sqlite as auth
import claim_agent.db.schema_privacy_sqlite as priv


# ---------------------------------------------------------------------------
# Helpers (mirrors test_schema_incidents_parity.py)
# ---------------------------------------------------------------------------

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _migration_text(filename: str) -> str:
    return (_VERSIONS_DIR / filename).read_text(encoding="utf-8")


def _table_body_from_create(sql: str, table: str) -> str:
    """Return the parenthesized body for ``CREATE TABLE [IF NOT EXISTS] <table> (``."""
    for marker in (
        f"CREATE TABLE IF NOT EXISTS {table} (",
        f"CREATE TABLE {table} (",
    ):
        start = sql.find(marker)
        if start != -1:
            i = start + len(marker)
            depth = 1
            while i < len(sql) and depth:
                c = sql[i]
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                i += 1
            assert depth == 0, f"unbalanced parentheses for {table!r}"
            return sql[start + len(marker) : i - 1]
    raise AssertionError(f"table {table!r} not found in DDL source")


def _physical_column_names(body: str) -> set[str]:
    """Column names from a CREATE TABLE body (skip table-level constraints)."""
    names: set[str] = set()
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        ul = line.upper()
        if (
            ul.startswith("FOREIGN KEY")
            or ul.startswith("UNIQUE ")
            or ul.startswith("CONSTRAINT ")
        ):
            continue
        if ul.startswith("PRIMARY KEY ") and "(" in line:
            parts = line.split()
            if parts[0].upper() == "PRIMARY" and parts[1].upper() == "KEY":
                continue
        line = line.rstrip(",").strip()
        if not line or line == ")":
            continue
        first = line.split()[0]
        names.add(first)
    return names


# ---------------------------------------------------------------------------
# Auth tables: revision 048
# ---------------------------------------------------------------------------

_rev048 = _migration_text("048_users_and_refresh_tokens.py")


def test_users_columns_match_048_postgres() -> None:
    """USERS_TABLE_SQLITE columns match migration 048 PostgreSQL DDL."""
    sqlite_body = _table_body_from_create(auth.USERS_TABLE_SQLITE, "users")
    pg_body = _table_body_from_create(_rev048, "users")
    assert _physical_column_names(sqlite_body) == _physical_column_names(pg_body)


def test_refresh_tokens_columns_match_048_postgres() -> None:
    """REFRESH_TOKENS_TABLE_SQLITE columns match migration 048 PostgreSQL DDL."""
    sqlite_body = _table_body_from_create(auth.REFRESH_TOKENS_TABLE_SQLITE, "refresh_tokens")
    pg_body = _table_body_from_create(_rev048, "refresh_tokens")
    assert _physical_column_names(sqlite_body) == _physical_column_names(pg_body)


# ---------------------------------------------------------------------------
# Privacy tables: dsar_verification_tokens – revision 046
# ---------------------------------------------------------------------------

_rev046 = _migration_text("046_dsar_verification_tokens.py")


def test_dsar_verification_tokens_columns_match_046_postgres() -> None:
    """DSAR_VERIFICATION_TOKENS_TABLE_SQLITE columns match migration 046 PostgreSQL DDL."""
    sqlite_body = _table_body_from_create(
        priv.DSAR_VERIFICATION_TOKENS_TABLE_SQLITE, "dsar_verification_tokens"
    )
    pg_body = _table_body_from_create(_rev046, "dsar_verification_tokens")
    assert _physical_column_names(sqlite_body) == _physical_column_names(pg_body)


# ---------------------------------------------------------------------------
# Privacy tables: dpa_registry + cross_border_transfer_log – revision 047
# ---------------------------------------------------------------------------

_rev047 = _migration_text("047_dpa_registry_cross_border_tables.py")


def test_dpa_registry_columns_match_047_postgres() -> None:
    """DPA_REGISTRY_TABLE_SQLITE columns match migration 047 PostgreSQL DDL."""
    sqlite_body = _table_body_from_create(priv.DPA_REGISTRY_TABLE_SQLITE, "dpa_registry")
    pg_body = _table_body_from_create(_rev047, "dpa_registry")
    assert _physical_column_names(sqlite_body) == _physical_column_names(pg_body)


def test_cross_border_transfer_log_columns_match_047_postgres() -> None:
    """CROSS_BORDER_TRANSFER_LOG_TABLE_SQLITE columns match migration 047 PostgreSQL DDL."""
    sqlite_body = _table_body_from_create(
        priv.CROSS_BORDER_TRANSFER_LOG_TABLE_SQLITE, "cross_border_transfer_log"
    )
    pg_body = _table_body_from_create(_rev047, "cross_border_transfer_log")
    assert _physical_column_names(sqlite_body) == _physical_column_names(pg_body)
