"""One-time data migration script: SQLite → PostgreSQL.

Moves existing claims data from a SQLite database to PostgreSQL, preserving
all historical claims, audit logs, workflow runs, and related records.

Usage
-----
    python scripts/migrate_sqlite_to_postgres.py [OPTIONS]

Options
-------
    --sqlite-path PATH    Source SQLite database path.
                          Default: CLAIMS_DB_PATH env var, then data/claims.db.
    --pg-url URL          Target PostgreSQL connection URL.
                          Default: DATABASE_URL env var.
    --dry-run             Read and validate source data without writing to PostgreSQL.
    --validate            After migration, verify row counts match between source and target.
    --table TABLE         Migrate only this table (repeat to migrate multiple tables).
    --truncate            Truncate target tables before inserting. USE WITH CARE: destroys
                          any existing data in the PostgreSQL database.
    --batch-size N        Number of rows per INSERT batch (default: 500).
    --verbose             Enable debug logging.

Migration procedure
-------------------
1.  Ensure PostgreSQL schema is up-to-date::

        alembic upgrade head

2.  Run a dry-run first to confirm the source database is readable::

        python scripts/migrate_sqlite_to_postgres.py --dry-run

3.  Run the migration::

        python scripts/migrate_sqlite_to_postgres.py

4.  Validate row counts::

        python scripts/migrate_sqlite_to_postgres.py --validate

5.  Switch your application to PostgreSQL by setting DATABASE_URL and unsetting
    CLAIMS_DB_PATH in your .env file.

Rollback
--------
The migration script does **not** delete or modify the source SQLite database.
If you need to roll back:

*   Stop the application.
*   Unset DATABASE_URL and restore CLAIMS_DB_PATH in .env.
*   Restart the application – it will resume using the original SQLite database.

To wipe the PostgreSQL data and start over::

    alembic downgrade base
    alembic upgrade head
    python scripts/migrate_sqlite_to_postgres.py

Notes
-----
*   The script processes tables in foreign-key dependency order so referential
    integrity is maintained in the target database.
*   PostgreSQL SERIAL sequences are reset after bulk insertion so that new rows
    receive IDs that do not collide with migrated rows.
*   Columns that exist in SQLite but not in PostgreSQL (e.g. very old SQLite DBs
    with legacy columns) are silently skipped.
*   Columns that exist in PostgreSQL but not in SQLite are left at their default
    values.
*   The ``claim_audit_log`` and ``reserve_history`` append-only triggers are
    temporarily disabled during migration using ``ALTER TABLE ... DISABLE TRIGGER USER``
    (user-defined triggers only; does not require superuser). Triggers are re-enabled
    before ``COMMIT`` so a failed migration rolls back trigger state with the transaction.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

logger = logging.getLogger("migrate_sqlite_to_postgres")

# ---------------------------------------------------------------------------
# Table dependency order (respecting FK constraints).
# Tables referenced by others must appear before those that reference them.
# ---------------------------------------------------------------------------

#: All tables handled by this script, in the order they must be migrated.
TABLES_IN_ORDER: list[str] = [
    # No FK dependencies
    "incidents",
    # Claims is the central table – almost everything references it
    "claims",
    # Tables that reference claims
    "claim_links",
    "claim_audit_log",
    "workflow_runs",
    "task_checkpoints",
    "claim_notes",
    "follow_up_messages",
    "reserve_history",
    "document_requests",
    "claim_tasks",  # also references document_requests and itself (parent_task_id)
    "claim_documents",
    "claim_parties",
    "claim_party_relationships",  # references claim_parties
    "claim_payments",  # references claims and claim_parties
    "subrogation_cases",
    "repair_status",
    # DSAR tables – no dependency on claims
    "dsar_requests",
    "dsar_exports",  # references dsar_requests
    "dsar_audit_log",
    # Access tokens reference claims and claim_parties
    "claim_access_tokens",
    # Standalone tables
    "idempotency_keys",
    "fraud_report_filings",
]

#: Tables with a TEXT primary key – no PostgreSQL sequence reset needed.
TEXT_PK_TABLES: frozenset[str] = frozenset({"incidents", "claims", "idempotency_keys"})

#: Append-only tables protected by triggers.  We temporarily disable the
#: triggers so bulk INSERT is allowed, then re-enable them.
APPEND_ONLY_TABLES: frozenset[str] = frozenset({"claim_audit_log", "reserve_history"})

# ---------------------------------------------------------------------------
# Helper: determine default paths from environment
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent


def _default_sqlite_path() -> str:
    path = os.environ.get("CLAIMS_DB_PATH", "")
    if path:
        p = Path(path)
        return str(p) if p.is_absolute() else str(_PROJECT_ROOT / p)
    return str(_PROJECT_ROOT / "data" / "claims.db")


def _default_pg_url() -> str:
    return os.environ.get("DATABASE_URL", "")


# ---------------------------------------------------------------------------
# Identifier validation
# ---------------------------------------------------------------------------

#: Set of allowed table names – used to guard against SQL injection when table
#: names are interpolated into SQL strings.
_ALLOWED_TABLES: frozenset[str] = frozenset(TABLES_IN_ORDER)

#: Pattern for a valid SQL identifier (letters, digits, underscores only).
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check_table_name(table: str) -> None:
    """Raise ValueError if *table* is not a known, safe table name."""
    if table not in _ALLOWED_TABLES:
        raise ValueError(
            f"Unknown or disallowed table name: {table!r}. "
            f"Allowed tables: {sorted(_ALLOWED_TABLES)}"
        )


def _check_column_name(col: str) -> None:
    """Raise ValueError if *col* does not look like a safe SQL identifier."""
    if not _IDENT_RE.match(col):
        raise ValueError(f"Unsafe column name: {col!r}")


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------


def _sqlite_get_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """Return column names for *table* in the SQLite database."""
    _check_table_name(table)
    cursor = conn.execute(f"PRAGMA table_info({table})")  # noqa: S608
    return [row[1] for row in cursor.fetchall()]


def _sqlite_table_exists(conn: sqlite3.Connection, table: str) -> bool:
    cursor = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return cursor.fetchone() is not None


def _sqlite_row_count(conn: sqlite3.Connection, table: str) -> int:
    _check_table_name(table)
    row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
    return row[0] if row else 0


# ---------------------------------------------------------------------------
# PostgreSQL helpers
# ---------------------------------------------------------------------------


def _pg_get_columns(pg_conn: Any, table: str) -> list[str]:
    """Return column names for *table* in the PostgreSQL database."""
    _check_table_name(table)
    cur = pg_conn.cursor()
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table,),
    )
    return [row[0] for row in cur.fetchall()]


def _pg_table_exists(pg_conn: Any, table: str) -> bool:
    cur = pg_conn.cursor()
    cur.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
        (table,),
    )
    return cur.fetchone() is not None


def _pg_row_count(pg_conn: Any, table: str) -> int:
    _check_table_name(table)
    cur = pg_conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM {table}")  # noqa: S608
    row = cur.fetchone()
    return row[0] if row else 0


def _pg_reset_sequence(pg_conn: Any, table: str) -> None:
    """Reset the SERIAL/IDENTITY sequence for *table*.id so new rows don't collide."""
    _check_table_name(table)
    cur = pg_conn.cursor()
    cur.execute(
        "SELECT pg_get_serial_sequence(%s, %s)",
        (f"public.{table}", "id"),
    )
    row = cur.fetchone()
    seq = row[0] if row else None
    if not seq:
        logger.warning(
            "No serial sequence for public.%s.id (pg_get_serial_sequence returned NULL) — "
            "skipping sequence reset; verify identity columns or non-standard PK names.",
            table,
        )
        return
    cur.execute(
        f"""
        SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)
        """,  # noqa: S608
        (seq,),
    )
    logger.debug("Reset sequence %s for table %s", seq, table)


def _pg_disable_append_only_triggers(pg_conn: Any, table: str) -> None:
    """Temporarily disable user-defined triggers on *table* (append-only guards)."""
    _check_table_name(table)
    cur = pg_conn.cursor()
    # USER: user-defined triggers only; table owner can run (no superuser required).
    cur.execute(f"ALTER TABLE {table} DISABLE TRIGGER USER")  # noqa: S608
    logger.debug("Disabled user triggers on %s", table)


def _pg_enable_append_only_triggers(pg_conn: Any, table: str) -> None:
    """Re-enable user-defined triggers on *table* after bulk insert."""
    _check_table_name(table)
    cur = pg_conn.cursor()
    cur.execute(f"ALTER TABLE {table} ENABLE TRIGGER USER")  # noqa: S608
    logger.debug("Enabled user triggers on %s", table)


def _inserted_rowcount(pg_cur: Any, batch_len: int) -> int:
    """Return rows inserted in the last batch.

    Always returns batch_len because cursor.rowcount after execute_batch is unreliable:
    psycopg2's execute_batch splits parameters into pages (default 100) and rowcount
    only reflects the last page, not the cumulative total.
    See: https://www.psycopg.org/docs/cursor.html and psycopg2 issue #540.
    """
    return batch_len


# ---------------------------------------------------------------------------
# Core migration logic
# ---------------------------------------------------------------------------


def _migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Any,
    table: str,
    *,
    dry_run: bool,
    truncate: bool,
    batch_size: int,
) -> tuple[int, int]:
    """Migrate a single table from SQLite to PostgreSQL.

    Returns:
        (rows_read, rows_written) tuple.
    """
    import psycopg2.extras  # noqa: PLC0415

    # Validate table name against the whitelist to prevent SQL injection.
    _check_table_name(table)

    if not _sqlite_table_exists(sqlite_conn, table):
        logger.info("Table %s not found in SQLite – skipping", table)
        return 0, 0

    if not dry_run and not _pg_table_exists(pg_conn, table):
        logger.warning("Table %s not found in PostgreSQL – skipping", table)
        return 0, 0

    # Determine which columns to migrate (intersection of SQLite and PG columns)
    sqlite_cols = _sqlite_get_columns(sqlite_conn, table)
    pg_cols_set = set(_pg_get_columns(pg_conn, table)) if not dry_run else set(sqlite_cols)

    if not sqlite_cols:
        logger.info("Table %s has no columns in SQLite – skipping", table)
        return 0, 0

    # Only migrate columns that exist in both databases.
    # Column names come from sqlite3 PRAGMA / information_schema (trusted sources), but
    # validate the pattern as a belt-and-suspenders guard.
    cols_to_migrate = []
    for c in sqlite_cols:
        if c in pg_cols_set:
            _check_column_name(c)  # guard: raises if column name is not a safe identifier
            cols_to_migrate.append(c)
    skipped = [c for c in sqlite_cols if c not in pg_cols_set]
    if skipped:
        logger.debug(
            "Table %s: skipping SQLite-only columns: %s", table, ", ".join(skipped)
        )

    if not cols_to_migrate:
        logger.warning("Table %s: no common columns between SQLite and PostgreSQL", table)
        return 0, 0

    logger.info("Migrating table: %s (columns: %s)", table, ", ".join(cols_to_migrate))

    if dry_run:
        # Count rows without loading the full table into memory.
        row = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
        rows_read = int(row[0]) if row else 0
        logger.info("  [DRY RUN] Would migrate %d rows from %s", rows_read, table)
        return rows_read, 0

    # Read all rows from SQLite
    sqlite_conn.row_factory = sqlite3.Row
    cursor = sqlite_conn.execute(  # noqa: S608
        f"SELECT {', '.join(cols_to_migrate)} FROM {table}"
    )
    sqlite_conn.row_factory = None

    rows_read = 0
    rows_inserted = 0
    append_only = table in APPEND_ONLY_TABLES

    try:
        if truncate:
            pg_conn.cursor().execute(f"TRUNCATE TABLE {table} CASCADE")  # noqa: S608
            logger.info("  Truncated %s", table)

        if append_only:
            _pg_disable_append_only_triggers(pg_conn, table)

        col_placeholders = ", ".join(["%s"] * len(cols_to_migrate))
        col_names = ", ".join(cols_to_migrate)
        insert_sql = (
            f"INSERT INTO {table} ({col_names}) VALUES ({col_placeholders}) "  # noqa: S608
            f"ON CONFLICT DO NOTHING"
        )

        batch: list[tuple[Any, ...]] = []
        pg_cur = pg_conn.cursor()

        for row in cursor:
            rows_read += 1
            batch.append(tuple(row))
            if len(batch) >= batch_size:
                psycopg2.extras.execute_batch(pg_cur, insert_sql, batch)
                rows_inserted += _inserted_rowcount(pg_cur, len(batch))
                batch = []
                logger.debug("  Inserted batch; total so far: %d", rows_inserted)

        if batch:
            psycopg2.extras.execute_batch(pg_cur, insert_sql, batch)
            rows_inserted += _inserted_rowcount(pg_cur, len(batch))

        if rows_inserted < rows_read:
            logger.warning(
                "  Table %s: inserted %d row(s), source had %d — possible ON CONFLICT skips "
                "(duplicate keys in target).",
                table,
                rows_inserted,
                rows_read,
            )

        # Reset sequence for SERIAL PK tables
        if table not in TEXT_PK_TABLES:
            _pg_reset_sequence(pg_conn, table)

        if append_only:
            _pg_enable_append_only_triggers(pg_conn, table)

        pg_conn.commit()
        logger.info("  Migrated %d rows to %s", rows_inserted, table)

    except Exception:
        pg_conn.rollback()
        raise

    return rows_read, rows_inserted


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(
    sqlite_conn: sqlite3.Connection,
    pg_conn: Any,
    tables: list[str],
) -> bool:
    """Compare row counts between SQLite and PostgreSQL for each table.

    Returns True if all counts match, False otherwise.
    """
    all_match = True
    logger.info("=== Validation: comparing row counts ===")
    for table in tables:
        if not _sqlite_table_exists(sqlite_conn, table):
            continue
        if not _pg_table_exists(pg_conn, table):
            logger.warning("  MISSING in PG: %s", table)
            all_match = False
            continue

        sqlite_count = _sqlite_row_count(sqlite_conn, table)
        pg_count = _pg_row_count(pg_conn, table)

        if sqlite_count == pg_count:
            logger.info("  OK     %-35s  %d rows", table, sqlite_count)
        else:
            logger.warning(
                "  MISMATCH %-35s  SQLite=%d  PostgreSQL=%d",
                table,
                sqlite_count,
                pg_count,
            )
            all_match = False

    return all_match


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate claims data from SQLite to PostgreSQL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--sqlite-path",
        default=None,
        help=(
            "Source SQLite database path. "
            "Default: CLAIMS_DB_PATH env var or data/claims.db."
        ),
    )
    parser.add_argument(
        "--pg-url",
        default=None,
        help="Target PostgreSQL URL. Default: DATABASE_URL env var.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and validate source data without writing to PostgreSQL.",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="After migration, verify row counts match between source and target.",
    )
    parser.add_argument(
        "--table",
        action="append",
        dest="tables",
        metavar="TABLE",
        help=(
            "Migrate only this table (repeat for multiple tables). "
            "Default: all tables."
        ),
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Truncate target tables before inserting (destroys existing PostgreSQL data).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of rows per INSERT batch (default: 500).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    """Run the migration.  Returns exit code (0 = success, 1 = failure)."""
    args = _parse_args(argv)

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )

    sqlite_path = args.sqlite_path or _default_sqlite_path()
    pg_url = args.pg_url or _default_pg_url()

    # Resolve which tables to migrate
    user_tables = args.tables
    if user_tables:
        # Validate that all requested tables are known
        invalid_tables = sorted({t for t in user_tables if t not in TABLES_IN_ORDER})
        if invalid_tables:
            logger.error(
                "Unknown table(s) requested via --table: %s. Allowed tables are: %s",
                ", ".join(invalid_tables),
                ", ".join(TABLES_IN_ORDER),
            )
            return 1
        # Preserve dependency order even when --table selects a valid subset
        tables = [t for t in TABLES_IN_ORDER if t in user_tables]
    else:
        tables = list(TABLES_IN_ORDER)

    # Validate inputs
    if not Path(sqlite_path).exists():
        logger.error("SQLite database not found: %s", sqlite_path)
        return 1

    if not pg_url and not args.dry_run:
        logger.error(
            "PostgreSQL URL is required. Set DATABASE_URL or pass --pg-url. "
            "Use --dry-run to validate SQLite data without a PostgreSQL connection."
        )
        return 1

    if pg_url and not (pg_url.startswith("postgresql") or pg_url.startswith("postgres")):
        logger.error(
            "DATABASE_URL does not look like a PostgreSQL URL: %r. "
            "Expected 'postgresql://' or 'postgres://'.",
            pg_url,
        )
        return 1

    logger.info("Source SQLite : %s", sqlite_path)
    if args.dry_run:
        logger.info("Mode          : DRY RUN (no writes to PostgreSQL)")
    else:
        logger.info("Target PG URL : %s", pg_url)
        logger.info("Mode          : LIVE migration")
    logger.info("Tables        : %s", ", ".join(tables))
    logger.info("Batch size    : %d", args.batch_size)

    try:
        sqlite_conn = sqlite3.connect(sqlite_path)
        sqlite_conn.execute("PRAGMA foreign_keys = OFF")
    except Exception as exc:
        logger.error("Failed to open SQLite database: %s", exc)
        return 1

    pg_conn = None
    if not args.dry_run:
        try:
            import psycopg2  # noqa: PLC0415

            pg_conn = psycopg2.connect(pg_url)
            pg_conn.autocommit = False
        except Exception as exc:
            logger.error("Failed to connect to PostgreSQL: %s", exc)
            sqlite_conn.close()
            return 1

    total_read = 0
    total_written = 0
    failed_tables: list[str] = []

    try:
        for table in tables:
            try:
                read, written = _migrate_table(
                    sqlite_conn,
                    pg_conn,
                    table,
                    dry_run=args.dry_run,
                    truncate=args.truncate,
                    batch_size=args.batch_size,
                )
                total_read += read
                total_written += written
            except Exception as exc:
                logger.error("Error migrating table %s: %s", table, exc)
                failed_tables.append(table)

        # Validation pass (reads both DBs; no writes)
        if args.validate and not args.dry_run and pg_conn is not None:
            ok = _validate(sqlite_conn, pg_conn, tables)
            if not ok:
                logger.warning("Validation detected mismatches – review the output above.")
                failed_tables.append("__validation__")

    finally:
        sqlite_conn.close()
        if pg_conn is not None:
            pg_conn.close()

    logger.info(
        "Migration complete: %d rows read, %d rows written, %d table(s) failed.",
        total_read,
        total_written,
        len(failed_tables),
    )
    if failed_tables:
        logger.error("Failed tables: %s", ", ".join(failed_tables))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
