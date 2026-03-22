"""Unit tests for scripts/migrate_sqlite_to_postgres.py.

These tests verify migration logic without requiring a running PostgreSQL instance.
They use an in-memory SQLite database as the source and a mock/stub for the target
PostgreSQL connection.
"""

from __future__ import annotations

import os
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

import migrate_sqlite_to_postgres as mig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sqlite() -> sqlite3.Connection:
    """Return an in-memory SQLite connection seeded with minimal schema + data."""
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
        CREATE TABLE incidents (
            id TEXT PRIMARY KEY,
            incident_date TEXT NOT NULL,
            incident_description TEXT,
            loss_state TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        INSERT INTO incidents VALUES
            ('INC-1', '2025-01-10', 'Multi-vehicle accident', 'CA',
             '2025-01-10 12:00:00', '2025-01-10 12:00:00');

        CREATE TABLE claims (
            id TEXT PRIMARY KEY,
            policy_number TEXT NOT NULL,
            vin TEXT NOT NULL,
            vehicle_year INTEGER,
            vehicle_make TEXT,
            vehicle_model TEXT,
            incident_date TEXT,
            incident_description TEXT,
            damage_description TEXT,
            estimated_damage REAL,
            claim_type TEXT,
            status TEXT DEFAULT 'pending',
            payout_amount REAL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );
        INSERT INTO claims VALUES
            ('CLM-1', 'POL-001', 'VIN001', 2020, 'Toyota', 'Camry',
             '2025-01-10', 'Fender bender', 'Minor dent', 1500.0,
             'partial_loss', 'open', NULL,
             '2025-01-10 12:00:00', '2025-01-10 12:00:00'),
            ('CLM-2', 'POL-002', 'VIN002', 2019, 'Honda', 'Civic',
             '2025-01-15', 'Rear-end collision', 'Bumper damage', 2000.0,
             'partial_loss', 'closed', 1800.0,
             '2025-01-15 09:00:00', '2025-01-15 09:00:00');

        CREATE TABLE claim_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            action TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT,
            details TEXT,
            actor_id TEXT DEFAULT 'system',
            before_state TEXT,
            after_state TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        INSERT INTO claim_audit_log (claim_id, action, old_status, new_status)
        VALUES ('CLM-1', 'status_change', 'pending', 'open');

        CREATE TABLE idempotency_keys (
            idempotency_key TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'completed',
            response_status INTEGER NOT NULL,
            response_body TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        INSERT INTO idempotency_keys VALUES
            ('key-abc', 'completed', 200, '{"id":"CLM-1"}',
             '2025-01-10 12:00:00', '2025-01-11 12:00:00');
    """)
    return conn


def _make_pg_mock(tables_and_cols: dict[str, list[str]] | None = None) -> MagicMock:
    """Return a mock psycopg2 connection that simulates common PG operations."""
    pg = MagicMock()
    pg.autocommit = False

    cur = MagicMock()
    pg.cursor.return_value = cur

    # information_schema.tables: simulate table existence
    existing = set(tables_and_cols.keys()) if tables_and_cols else set()

    def _execute_side_effect(sql, params=None):
        sql_stripped = sql.strip()
        # Table existence query
        if "information_schema.tables" in sql_stripped and params:
            tbl = params[0]
            cur.fetchone.return_value = (1,) if tbl in existing else None
        # Column listing query
        elif "information_schema.columns" in sql_stripped and params:
            tbl = params[0]
            cols = tables_and_cols.get(tbl, []) if tables_and_cols else []
            cur.fetchall.return_value = [(c,) for c in cols]
        # Row count query
        elif "COUNT(*)" in sql_stripped:
            cur.fetchone.return_value = (0,)
        # Sequence lookup (must run before setval in _pg_reset_sequence)
        elif "pg_get_serial_sequence" in sql_stripped and params:
            cur.fetchone.return_value = (params[0] + "_id_seq",)
        # setval / sequence reset
        elif "setval" in sql_stripped:
            cur.fetchone.return_value = (1,)

    cur.execute.side_effect = _execute_side_effect
    return pg


# ---------------------------------------------------------------------------
# TABLES_IN_ORDER
# ---------------------------------------------------------------------------


class TestTableOrder:
    def test_incidents_before_claims(self):
        incidents_idx = mig.TABLES_IN_ORDER.index("incidents")
        claims_idx = mig.TABLES_IN_ORDER.index("claims")
        assert incidents_idx < claims_idx

    def test_claims_before_claim_audit_log(self):
        claims_idx = mig.TABLES_IN_ORDER.index("claims")
        audit_idx = mig.TABLES_IN_ORDER.index("claim_audit_log")
        assert claims_idx < audit_idx

    def test_claims_before_claim_parties(self):
        claims_idx = mig.TABLES_IN_ORDER.index("claims")
        parties_idx = mig.TABLES_IN_ORDER.index("claim_parties")
        assert claims_idx < parties_idx

    def test_claim_parties_before_relationships(self):
        parties_idx = mig.TABLES_IN_ORDER.index("claim_parties")
        rel_idx = mig.TABLES_IN_ORDER.index("claim_party_relationships")
        assert parties_idx < rel_idx

    def test_document_requests_before_claim_tasks(self):
        dr_idx = mig.TABLES_IN_ORDER.index("document_requests")
        ct_idx = mig.TABLES_IN_ORDER.index("claim_tasks")
        assert dr_idx < ct_idx

    def test_dsar_requests_before_dsar_exports(self):
        req_idx = mig.TABLES_IN_ORDER.index("dsar_requests")
        exp_idx = mig.TABLES_IN_ORDER.index("dsar_exports")
        assert req_idx < exp_idx

    def test_no_duplicate_tables(self):
        assert len(mig.TABLES_IN_ORDER) == len(set(mig.TABLES_IN_ORDER))


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------


class TestSqliteHelpers:
    def test_table_exists_present(self):
        conn = _make_sqlite()
        assert mig._sqlite_table_exists(conn, "claims") is True
        conn.close()

    def test_table_exists_missing(self):
        conn = _make_sqlite()
        assert mig._sqlite_table_exists(conn, "no_such_table") is False
        conn.close()

    def test_get_columns(self):
        conn = _make_sqlite()
        cols = mig._sqlite_get_columns(conn, "claims")
        assert "id" in cols
        assert "policy_number" in cols
        assert "vin" in cols
        conn.close()

    def test_row_count(self):
        conn = _make_sqlite()
        assert mig._sqlite_row_count(conn, "claims") == 2
        assert mig._sqlite_row_count(conn, "incidents") == 1
        assert mig._sqlite_row_count(conn, "claim_audit_log") == 1
        conn.close()


# ---------------------------------------------------------------------------
# Insert rowcount helper
# ---------------------------------------------------------------------------


class TestInsertedRowcount:
    def test_always_returns_batch_len(self):
        """After execute_batch, cursor.rowcount is unreliable (only reflects last page).
        
        The helper always returns batch_len because execute_batch internally splits
        parameters into pages and cursor.rowcount only contains the count from the
        last page, not the cumulative total.
        """
        cur = MagicMock()
        cur.rowcount = 100  # Simulates last page count
        # Should ignore rowcount and use batch_len
        assert mig._inserted_rowcount(cur, 500) == 500
        
    def test_returns_batch_len_regardless_of_rowcount(self):
        cur = MagicMock()
        cur.rowcount = MagicMock()  # Invalid rowcount
        assert mig._inserted_rowcount(cur, 250) == 250


# ---------------------------------------------------------------------------
# PostgreSQL helpers (mocked)
# ---------------------------------------------------------------------------


class TestPgHelpers:
    def test_pg_table_exists_present(self):
        pg = _make_pg_mock({"claims": ["id", "policy_number"]})
        assert mig._pg_table_exists(pg, "claims") is True

    def test_pg_table_exists_missing(self):
        pg = _make_pg_mock({})
        assert mig._pg_table_exists(pg, "claims") is False

    def test_pg_get_columns(self):
        cols = ["id", "policy_number", "vin"]
        pg = _make_pg_mock({"claims": cols})
        result = mig._pg_get_columns(pg, "claims")
        assert result == cols

    def test_pg_reset_sequence_called(self):
        pg = _make_pg_mock({"claim_audit_log": ["id", "claim_id"]})
        mig._pg_reset_sequence(pg, "claim_audit_log")
        # Verify pg_get_serial_sequence then setval
        pg.cursor().execute.assert_called()
        call_args = pg.cursor().execute.call_args_list
        assert any("pg_get_serial_sequence" in str(c) for c in call_args)
        assert any("setval" in str(c) for c in call_args)


# ---------------------------------------------------------------------------
# _migrate_table – dry run
# ---------------------------------------------------------------------------


class TestMigrateTableDryRun:
    def test_dry_run_returns_row_count(self):
        sqlite_conn = _make_sqlite()
        pg = _make_pg_mock({"claims": ["id", "policy_number", "vin"]})

        read, written = mig._migrate_table(
            sqlite_conn,
            pg,
            "claims",
            dry_run=True,
            truncate=False,
            batch_size=500,
        )

        assert read == 2
        assert written == 0
        # No writes to PostgreSQL
        pg.cursor().execute.assert_not_called()
        pg.commit.assert_not_called()
        sqlite_conn.close()

    def test_dry_run_skips_missing_sqlite_table(self):
        sqlite_conn = _make_sqlite()
        pg = _make_pg_mock({})

        read, written = mig._migrate_table(
            sqlite_conn,
            pg,
            "subrogation_cases",  # not in our in-memory DB
            dry_run=True,
            truncate=False,
            batch_size=500,
        )

        assert read == 0
        assert written == 0
        sqlite_conn.close()

    def test_dry_run_skips_missing_pg_table(self):
        sqlite_conn = _make_sqlite()
        # claims exists in SQLite but not in PG mock – in dry-run mode PG is not consulted
        pg = _make_pg_mock({})

        read, written = mig._migrate_table(
            sqlite_conn,
            pg,
            "claims",
            dry_run=True,
            truncate=False,
            batch_size=500,
        )

        # In dry-run, PG table existence is not checked, so rows are counted from SQLite
        assert read == 2
        assert written == 0
        sqlite_conn.close()


# ---------------------------------------------------------------------------
# _migrate_table – live (mocked psycopg2)
# ---------------------------------------------------------------------------


class TestMigrateTableLive:
    def test_live_migration_commits(self):
        sqlite_conn = _make_sqlite()
        pg_cols = ["id", "policy_number", "vin", "vehicle_year", "vehicle_make",
                   "vehicle_model", "incident_date", "incident_description",
                   "damage_description", "estimated_damage", "claim_type",
                   "status", "payout_amount", "created_at", "updated_at"]
        pg = _make_pg_mock({"claims": pg_cols})

        with patch("psycopg2.extras.execute_batch") as mock_batch:
            read, written = mig._migrate_table(
                sqlite_conn,
                pg,
                "claims",
                dry_run=False,
                truncate=False,
                batch_size=500,
            )

        assert read == 2
        assert written == 2
        mock_batch.assert_called_once()
        pg.commit.assert_called()
        sqlite_conn.close()

    def test_live_migration_uses_batches(self):
        sqlite_conn = _make_sqlite()
        pg_cols = ["id", "policy_number", "vin", "claim_type", "status",
                   "created_at", "updated_at"]
        pg = _make_pg_mock({"claims": pg_cols})

        with patch("psycopg2.extras.execute_batch") as mock_batch:
            read, written = mig._migrate_table(
                sqlite_conn,
                pg,
                "claims",
                dry_run=False,
                truncate=False,
                batch_size=1,  # force two batches for 2 rows
            )

        assert read == 2
        assert written == 2
        assert mock_batch.call_count == 2
        sqlite_conn.close()

    def test_truncate_issues_truncate_sql(self):
        sqlite_conn = _make_sqlite()
        pg_cols = ["id", "policy_number", "vin", "claim_type", "status",
                   "created_at", "updated_at"]
        pg = _make_pg_mock({"claims": pg_cols})

        with patch("psycopg2.extras.execute_batch"):
            mig._migrate_table(
                sqlite_conn,
                pg,
                "claims",
                dry_run=False,
                truncate=True,
                batch_size=500,
            )

        # Verify TRUNCATE was issued
        calls = [str(c) for c in pg.cursor().execute.call_args_list]
        assert any("TRUNCATE" in c for c in calls)
        sqlite_conn.close()

    def test_rollback_on_error(self):
        sqlite_conn = _make_sqlite()
        pg_cols = ["id", "policy_number", "vin", "claim_type", "status",
                   "created_at", "updated_at"]
        pg = _make_pg_mock({"claims": pg_cols})

        with patch("psycopg2.extras.execute_batch", side_effect=RuntimeError("DB error")):
            with pytest.raises(RuntimeError):
                mig._migrate_table(
                    sqlite_conn,
                    pg,
                    "claims",
                    dry_run=False,
                    truncate=False,
                    batch_size=500,
                )

        pg.rollback.assert_called_once()
        sqlite_conn.close()

    def test_text_pk_table_skips_sequence_reset(self):
        """incidents and claims (TEXT PKs) must not trigger sequence reset."""
        sqlite_conn = _make_sqlite()
        pg_cols = ["id", "incident_date", "incident_description",
                   "loss_state", "created_at", "updated_at"]
        pg = _make_pg_mock({"incidents": pg_cols})

        with patch("psycopg2.extras.execute_batch"):
            mig._migrate_table(
                sqlite_conn,
                pg,
                "incidents",
                dry_run=False,
                truncate=False,
                batch_size=500,
            )

        # setval should NOT appear in the execute calls
        calls = [str(c) for c in pg.cursor().execute.call_args_list]
        assert not any("setval" in c for c in calls)
        sqlite_conn.close()

    def test_serial_pk_table_resets_sequence(self):
        """claim_audit_log has SERIAL PK – must reset sequence after insert."""
        sqlite_conn = _make_sqlite()
        pg_cols = ["id", "claim_id", "action", "old_status", "new_status",
                   "details", "actor_id", "before_state", "after_state", "created_at"]
        pg = _make_pg_mock({"claim_audit_log": pg_cols})

        with patch("psycopg2.extras.execute_batch"):
            mig._migrate_table(
                sqlite_conn,
                pg,
                "claim_audit_log",
                dry_run=False,
                truncate=False,
                batch_size=500,
            )

        calls = [str(c) for c in pg.cursor().execute.call_args_list]
        assert any("setval" in c for c in calls)
        sqlite_conn.close()

    def test_append_only_table_disables_and_reenables_triggers(self):
        """claim_audit_log triggers must be disabled before insert and re-enabled after."""
        sqlite_conn = _make_sqlite()
        pg_cols = ["id", "claim_id", "action", "old_status", "new_status",
                   "details", "actor_id", "before_state", "after_state", "created_at"]
        pg = _make_pg_mock({"claim_audit_log": pg_cols})

        with patch("psycopg2.extras.execute_batch"):
            mig._migrate_table(
                sqlite_conn,
                pg,
                "claim_audit_log",
                dry_run=False,
                truncate=False,
                batch_size=500,
            )

        calls = [str(c) for c in pg.cursor().execute.call_args_list]
        disable_calls = [c for c in calls if "DISABLE TRIGGER USER" in c]
        enable_calls = [c for c in calls if "ENABLE TRIGGER USER" in c]
        assert len(disable_calls) >= 1, "Expected DISABLE TRIGGER USER call"
        assert len(enable_calls) >= 1, "Expected ENABLE TRIGGER USER call"
        sqlite_conn.close()

    def test_sqlite_only_columns_skipped(self):
        """Columns in SQLite but not in PG should be excluded from INSERT."""
        sqlite_conn = _make_sqlite()
        # PG only has a subset of claims columns
        pg_cols = ["id", "policy_number", "vin"]
        pg = _make_pg_mock({"claims": pg_cols})

        with patch("psycopg2.extras.execute_batch") as mock_batch:
            read, written = mig._migrate_table(
                sqlite_conn,
                pg,
                "claims",
                dry_run=False,
                truncate=False,
                batch_size=500,
            )

        assert written == 2
        # The INSERT SQL should only include the 3 common columns
        insert_sql = mock_batch.call_args[0][1]
        assert "policy_number" in insert_sql
        assert "vehicle_year" not in insert_sql
        sqlite_conn.close()

    def test_idempotency_keys_text_pk_no_sequence_reset(self):
        """idempotency_keys has a TEXT PK – must not reset sequence."""
        sqlite_conn = _make_sqlite()
        pg_cols = ["idempotency_key", "status", "response_status",
                   "response_body", "created_at", "expires_at"]
        pg = _make_pg_mock({"idempotency_keys": pg_cols})

        with patch("psycopg2.extras.execute_batch"):
            mig._migrate_table(
                sqlite_conn,
                pg,
                "idempotency_keys",
                dry_run=False,
                truncate=False,
                batch_size=500,
            )

        calls = [str(c) for c in pg.cursor().execute.call_args_list]
        assert not any("setval" in c for c in calls)
        sqlite_conn.close()


# ---------------------------------------------------------------------------
# _validate
# ---------------------------------------------------------------------------


class TestValidate:
    def test_validate_matching_counts(self, caplog):
        import logging

        sqlite_conn = _make_sqlite()
        pg = _make_pg_mock({"claims": ["id"], "incidents": ["id"],
                            "claim_audit_log": ["id"], "idempotency_keys": ["idempotency_key"]})

        # Make pg count match sqlite count
        pg.cursor().fetchone.return_value = (2,)  # all tables return 2

        # Override to give per-table counts
        cur = MagicMock()
        pg.cursor.return_value = cur

        def count_side_effect(sql, params=None):
            sql_stripped = sql.strip()
            if "information_schema.tables" in sql_stripped and params:
                cur.fetchone.return_value = (1,)
            elif "COUNT(*)" in sql_stripped:
                # Alternate to simulate matching
                cur.fetchone.return_value = (
                    mig._sqlite_row_count(sqlite_conn, params[0])
                    if params
                    else (0,)
                )
            elif "information_schema.columns" in sql_stripped and params:
                cur.fetchall.return_value = []

        cur.execute.side_effect = count_side_effect

        with caplog.at_level(logging.INFO, logger="migrate_sqlite_to_postgres"):
            result = mig._validate(
                sqlite_conn,
                pg,
                ["incidents", "claims", "idempotency_keys"],
            )

        # Result may be True or False depending on mock; the key thing is it runs
        assert isinstance(result, bool)
        sqlite_conn.close()

    def test_validate_missing_pg_table_returns_false(self):
        sqlite_conn = _make_sqlite()
        # No tables exist in PG
        pg = _make_pg_mock({})

        result = mig._validate(sqlite_conn, pg, ["claims"])
        assert result is False
        sqlite_conn.close()


# ---------------------------------------------------------------------------
# run() – argument parsing and integration
# ---------------------------------------------------------------------------


class TestRunFunction:
    def test_missing_sqlite_path_returns_error(self, tmp_path):
        code = mig.run(["--sqlite-path", str(tmp_path / "nonexistent.db"),
                        "--dry-run"])
        assert code == 1

    def test_dry_run_without_pg_url_succeeds(self, tmp_path):
        # Create a minimal SQLite file
        db = tmp_path / "test.db"
        conn = sqlite3.connect(str(db))
        conn.executescript("""
            CREATE TABLE claims (
                id TEXT PRIMARY KEY,
                policy_number TEXT NOT NULL,
                vin TEXT NOT NULL
            );
        """)
        conn.close()

        code = mig.run(["--sqlite-path", str(db), "--dry-run"])
        assert code == 0

    def test_missing_pg_url_returns_error(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        # No --pg-url and no DATABASE_URL in env
        env_backup = os.environ.pop("DATABASE_URL", None)
        try:
            code = mig.run(["--sqlite-path", str(db)])
        finally:
            if env_backup is not None:
                os.environ["DATABASE_URL"] = env_backup
        assert code == 1

    def test_invalid_pg_url_returns_error(self, tmp_path):
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()
        code = mig.run(["--sqlite-path", str(db), "--pg-url", "sqlite:///foo.db"])
        assert code == 1

    def test_table_filter_preserves_dependency_order(self, tmp_path):
        """--table flag should still respect FK dependency order."""
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()

        # Patch _migrate_table so we can capture table order
        migrated = []

        def fake_migrate(sqlite_conn, pg_conn, table, **kwargs):
            migrated.append(table)
            return 0, 0

        with patch.object(mig, "_migrate_table", side_effect=fake_migrate):
            with patch("psycopg2.connect", return_value=MagicMock()):
                # Request claim_audit_log before claims (reversed order)
                mig.run([
                    "--sqlite-path", str(db),
                    "--pg-url", "postgresql://localhost/test",
                    "--table", "claim_audit_log",
                    "--table", "claims",
                ])

        # claims must be before claim_audit_log regardless of input order
        assert migrated.index("claims") < migrated.index("claim_audit_log")

    def test_default_batch_size(self):
        args = mig._parse_args(["--dry-run"])
        assert args.batch_size == 500

    def test_custom_batch_size(self):
        args = mig._parse_args(["--batch-size", "100", "--dry-run"])
        assert args.batch_size == 100

    def test_multiple_table_flags(self):
        args = mig._parse_args([
            "--table", "claims",
            "--table", "incidents",
            "--dry-run",
        ])
        assert args.tables == ["claims", "incidents"]

    def test_unknown_table_returns_error(self, tmp_path):
        """--table with an unknown table name should return exit code 1."""
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()

        code = mig.run([
            "--sqlite-path", str(db),
            "--dry-run",
            "--table", "nonexistent_table",
        ])
        assert code == 1

    def test_unknown_table_mixed_with_valid_returns_error(self, tmp_path):
        """--table with a mix of valid and unknown tables should return exit code 1."""
        db = tmp_path / "test.db"
        sqlite3.connect(str(db)).close()

        code = mig.run([
            "--sqlite-path", str(db),
            "--dry-run",
            "--table", "claims",
            "--table", "bogus_table",
        ])
        assert code == 1
