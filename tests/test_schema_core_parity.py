"""Parity tests: core SQLite DDL constants vs. corresponding PostgreSQL migration DDL.

Verifies that ``CLAIMS_TABLE_SQLITE`` and ``CLAIM_AUDIT_LOG_TABLE_SQLITE`` in
``schema_core_sqlite.py`` stay aligned with the PostgreSQL schema built from:

  - ``023_postgres_full_schema.py`` – initial CREATE TABLE definitions
  - ``026_ucspa_compliance.py`` – UCSPA deadline and denial columns on ``claims``
  - ``029_litigation_hold_and_dsar_deletion.py`` – adds ``litigation_hold``
  - ``033_settlement_workflow_flags.py`` – adds ``repair_ready_for_settlement``,
    ``total_loss_settlement_authorized``
  - ``034_retention_tier_and_purge.py`` – adds ``retention_tier``, ``purged_at``
  - ``042_settlement_agreed_at.py`` – adds ``settlement_agreed_at``
  - ``043_incident_coordinates.py`` – adds ``incident_latitude``, ``incident_longitude``
  - ``044_communication_response_deadline.py`` – adds ``last_claimant_communication_at``,
    ``communication_response_due``
  - ``050_cold_storage_export.py`` – adds ``cold_storage_exported_at``,
    ``cold_storage_export_key``

Uses the same helpers as ``test_schema_incidents_parity.py`` and
``test_schema_sqlite_parity.py``.
"""

import re
from pathlib import Path

import claim_agent.db.schema_core_sqlite as core

# ---------------------------------------------------------------------------
# Helpers (mirrors test_schema_sqlite_parity.py)
# ---------------------------------------------------------------------------

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _migration_text(filename: str) -> str:
    return (_VERSIONS_DIR / filename).read_text(encoding="utf-8")


def _normalize_source(text: str) -> str:
    """Join Python implicit string concatenations split across adjacent lines.

    Turns ``"ADD COLUMN IF NOT EXISTS "\\n    "col_name TEXT"`` into
    ``"ADD COLUMN IF NOT EXISTS col_name TEXT"`` so that a single-pass
    regex can find the column name without being tripped up by the literal
    ``"`` boundary.
    """
    return re.sub(r'"\s*\n\s*"', "", text)


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


# Matches: ALTER TABLE claims ADD COLUMN [IF NOT EXISTS] <col_name>
_ADD_COLUMN_RE = re.compile(
    r"ALTER\s+TABLE\s+claims\s+ADD\s+COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+(\w+)",
    re.IGNORECASE,
)


def _postgres_branch(source: str) -> str:
    """Return only the ``else:`` (postgres) branch of ``upgrade()`` in *source*.

    Slices from the first ``else:`` that appears inside ``upgrade()`` up to
    (but not including) ``def downgrade``, so that :data:`_ADD_COLUMN_RE`
    matches are constrained to the postgres path and cannot accidentally pick
    up SQLite-only ``ALTER TABLE … ADD COLUMN`` statements.

    Returns an empty string when no ``else:`` block is found.
    """
    upgrade_pos = source.find("def upgrade(")
    if upgrade_pos == -1:
        return ""
    else_pos = source.find("\n    else:", upgrade_pos)
    if else_pos == -1:
        return ""
    downgrade_pos = source.find("\ndef downgrade", else_pos)
    end = downgrade_pos if downgrade_pos != -1 else len(source)
    return source[else_pos:end]


# Columns added in 026's postgres branch via f-string SQL; regex cannot expand ``{col}``.
_UCSPA_026_POSTGRES_CLAIM_COLUMNS = frozenset(
    {
        "acknowledged_at",
        "acknowledgment_due",
        "investigation_due",
        "payment_due",
        "denial_reason",
        "denial_letter_sent_at",
        "denial_letter_body",
    }
)


def _postgres_claims_columns() -> set[str]:
    """Build the full postgres ``claims`` column set.

    Combines the initial CREATE TABLE from revision 023 with the ADD COLUMN
    statements from later migrations that have a postgres-specific path
    (026, 029, 033, 034, 042, 043, 044, 050).  Migrations 014 and 016 return early for postgres
    because those columns were already included in 023.
    """
    pg023 = _migration_text("023_postgres_full_schema.py")
    cols = _physical_column_names(_table_body_from_create(pg023, "claims"))
    cols.update(_UCSPA_026_POSTGRES_CLAIM_COLUMNS)

    # Each of these migrations has an ``else`` / postgres-specific branch that
    # issues ``ALTER TABLE claims ADD COLUMN [IF NOT EXISTS] ...``.
    for filename in (
        "029_litigation_hold_and_dsar_deletion.py",
        "033_settlement_workflow_flags.py",
        "034_retention_tier_and_purge.py",
        "042_settlement_agreed_at.py",
        "043_incident_coordinates.py",
        "044_communication_response_deadline.py",
        "050_cold_storage_export.py",
    ):
        raw = _migration_text(filename)
        normalized = _normalize_source(_postgres_branch(raw))
        for m in _ADD_COLUMN_RE.finditer(normalized):
            name = m.group(1).lower()
            # f-string migrations (026) can leave ``IF NOT EXISTS {col}`` unparsed; skip false match.
            if name in {"if", "not", "exists"}:
                continue
            cols.add(name)

    return cols


# ---------------------------------------------------------------------------
# claims table
# ---------------------------------------------------------------------------


def test_claims_columns_match_postgres() -> None:
    """CLAIMS_TABLE_SQLITE columns match the cumulative postgres ``claims`` schema."""
    sqlite_body = _table_body_from_create(core.CLAIMS_TABLE_SQLITE, "claims")
    sqlite_cols = _physical_column_names(sqlite_body)
    pg_cols = _postgres_claims_columns()
    assert sqlite_cols == pg_cols, (
        f"Column mismatch between CLAIMS_TABLE_SQLITE and postgres:\n"
        f"  SQLite only: {sorted(sqlite_cols - pg_cols)}\n"
        f"  Postgres only: {sorted(pg_cols - sqlite_cols)}"
    )


# ---------------------------------------------------------------------------
# claim_audit_log table – revision 023 only (no later migrations add columns)
# ---------------------------------------------------------------------------

_rev023 = _migration_text("023_postgres_full_schema.py")


def test_claim_audit_log_columns_match_postgres_023() -> None:
    """CLAIM_AUDIT_LOG_TABLE_SQLITE columns match migration 023 PostgreSQL DDL."""
    sqlite_body = _table_body_from_create(
        core.CLAIM_AUDIT_LOG_TABLE_SQLITE, "claim_audit_log"
    )
    pg_body = _table_body_from_create(_rev023, "claim_audit_log")
    assert _physical_column_names(sqlite_body) == _physical_column_names(pg_body)
