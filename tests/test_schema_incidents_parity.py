"""Keep SQLite incidents DDL (bootstrap + Alembic 022) aligned with Postgres 023."""

from pathlib import Path

from claim_agent.db import schema_incidents_sqlite as sis


def _table_body_from_create(sql: str, table: str) -> str:
    """Return the parenthesized column/constraint body for ``CREATE TABLE ... name (``."""
    marker = f"CREATE TABLE IF NOT EXISTS {table} ("
    start = sql.find(marker)
    assert start != -1, f"missing {marker!r} in DDL source"
    i = start + len(marker)
    depth = 1
    while i < len(sql) and depth:
        c = sql[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    assert depth == 0
    return sql[start + len(marker) : i - 1]


def _physical_column_names(body: str) -> set[str]:
    """Column names from a CREATE TABLE body (skip table-level FK/UNIQUE/CONSTRAINT)."""
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
        if not line:
            continue
        first = line.split()[0]
        if first == ")":
            continue
        names.add(first)
    return names


def _postgres_full_schema_text() -> str:
    root = Path(__file__).resolve().parents[1]
    path = root / "alembic/versions/023_postgres_full_schema.py"
    return path.read_text(encoding="utf-8")


def test_incidents_columns_match_postgres_023() -> None:
    sqlite_body = _table_body_from_create(sis.INCIDENTS_TABLE_SQLITE, "incidents")
    pg_body = _table_body_from_create(_postgres_full_schema_text(), "incidents")
    assert _physical_column_names(sqlite_body) == _physical_column_names(pg_body)


def test_claim_links_columns_match_postgres_023() -> None:
    sqlite_body = _table_body_from_create(sis.CLAIM_LINKS_TABLE_SQLITE, "claim_links")
    pg_body = _table_body_from_create(_postgres_full_schema_text(), "claim_links")
    assert _physical_column_names(sqlite_body) == _physical_column_names(pg_body)
