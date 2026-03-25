"""Unit tests for scripts/backup_postgres.py and scripts/restore_postgres.py.

These tests verify backup/restore logic without requiring a running PostgreSQL
instance or pg_dump/pg_restore binaries.  All subprocess calls are mocked.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

import backup_postgres as bkp
import restore_postgres as rst


# ---------------------------------------------------------------------------
# backup_postgres helpers
# ---------------------------------------------------------------------------


class TestMaskUrlPassword:
    def test_masks_password(self):
        url = "postgresql://claims:supersecret@localhost:5432/claims"
        assert "supersecret" not in bkp._mask_url_password(url)
        assert "***" in bkp._mask_url_password(url)

    def test_no_password_unchanged(self):
        url = "postgresql://localhost/claims"
        assert bkp._mask_url_password(url) == url

    def test_fail_closed_on_bad_scheme(self):
        assert bkp._mask_url_password("redis://user:pass@localhost:6379/0") == "<redacted>"


class TestResolveBackupDir:
    def test_default_is_data_backups(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BACKUP_DIR", raising=False)
        result = bkp._resolve_backup_dir(None)
        # Should end with data/backups
        assert result.parts[-1] == "backups"
        assert result.parts[-2] == "data"

    def test_cli_arg_takes_precedence(self, tmp_path):
        result = bkp._resolve_backup_dir(str(tmp_path))
        assert result == tmp_path

    def test_env_var_used_when_no_cli(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        result = bkp._resolve_backup_dir(None)
        assert result == tmp_path


class TestResolveRetentionDays:
    def test_cli_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("BACKUP_RETENTION_DAYS", "7")
        assert bkp._resolve_retention_days(30) == 30

    def test_env_var_used(self, monkeypatch):
        monkeypatch.setenv("BACKUP_RETENTION_DAYS", "7")
        assert bkp._resolve_retention_days(None) == 7

    def test_default_is_14(self, monkeypatch):
        monkeypatch.delenv("BACKUP_RETENTION_DAYS", raising=False)
        assert bkp._resolve_retention_days(None) == 14

    def test_invalid_env_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BACKUP_RETENTION_DAYS", "notanumber")
        assert bkp._resolve_retention_days(None) == 14


class TestBackupFilename:
    def test_compressed_extension(self):
        name = bkp._backup_filename("claims", compress=True)
        assert name.endswith(".dump")
        assert name.startswith("claims_claims_")

    def test_plain_extension(self):
        name = bkp._backup_filename("claims", compress=False)
        assert name.endswith(".sql")

    def test_contains_timestamp(self):
        name = bkp._backup_filename("claims", compress=True)
        # Timestamp portion: YYYYMMDD_HHMMSS
        import re
        assert re.search(r"\d{8}_\d{6}", name)


class TestDbNameFromUrl:
    def test_extracts_db_name(self):
        assert bkp._db_name_from_url("postgresql://user:pass@host:5432/mydb") == "mydb"

    def test_defaults_to_claims(self):
        assert bkp._db_name_from_url("postgresql://host/") == "claims"


# ---------------------------------------------------------------------------
# backup_postgres.run_pg_dump
# ---------------------------------------------------------------------------


class TestRunPgDump:
    def test_calls_subprocess_correctly(self, tmp_path):
        output_path = tmp_path / "claims_20240101_020000.dump"
        # Create a stub file so stat() works
        output_path.write_bytes(b"PGDMP" + b"\x00" * 100)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            bkp.run_pg_dump(
                "postgresql://claims:secret@localhost/claims",
                output_path,
                "/usr/bin/pg_dump",
                compress=True,
            )

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        kwargs = mock_run.call_args.kwargs
        assert cmd[0] == "/usr/bin/pg_dump"
        assert "-Fc" in cmd
        assert "-h" in cmd
        assert "localhost" in cmd
        assert "-U" in cmd
        assert "claims" in cmd
        assert str(output_path) in cmd
        assert kwargs["env"].get("PGPASSWORD") == "secret"
        assert "timeout" in kwargs

    def test_dry_run_skips_subprocess(self, tmp_path):
        output_path = tmp_path / "test.dump"
        with patch("subprocess.run") as mock_run:
            bkp.run_pg_dump(
                "postgresql://localhost/claims",
                output_path,
                "pg_dump",
                compress=True,
                dry_run=True,
            )
        mock_run.assert_not_called()

    def test_raises_on_nonzero_exit(self, tmp_path):
        output_path = tmp_path / "test.dump"
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "connection refused"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="1"):
                bkp.run_pg_dump("postgresql://localhost/claims", output_path, "pg_dump", compress=True)

    def test_plain_format_uses_Fp_flag(self, tmp_path):
        output_path = tmp_path / "claims.sql"
        output_path.write_text("-- plain sql")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result) as mock_run:
            bkp.run_pg_dump("postgresql://localhost/claims", output_path, "pg_dump", compress=False)
        cmd = mock_run.call_args[0][0]
        assert "-Fp" in cmd


# ---------------------------------------------------------------------------
# backup_postgres.rotate_old_backups
# ---------------------------------------------------------------------------


class TestRotateOldBackups:
    def test_deletes_files_older_than_retention(self, tmp_path):
        import time

        old_file = tmp_path / "claims_claims_20200101_020000.dump"
        old_file.write_bytes(b"old")
        # Force mtime to be 30 days ago
        old_ts = time.time() - 30 * 86400
        os.utime(old_file, (old_ts, old_ts))

        new_file = tmp_path / "claims_claims_20991231_020000.dump"
        new_file.write_bytes(b"new")

        deleted = bkp.rotate_old_backups(tmp_path, retention_days=14)
        assert old_file in deleted
        assert not old_file.exists()
        assert new_file.exists()

    def test_dry_run_does_not_delete(self, tmp_path):
        import time

        old_file = tmp_path / "claims_claims_20200101_020000.dump"
        old_file.write_bytes(b"old")
        old_ts = time.time() - 30 * 86400
        os.utime(old_file, (old_ts, old_ts))

        deleted = bkp.rotate_old_backups(tmp_path, retention_days=14, dry_run=True)
        assert old_file in deleted
        assert old_file.exists()  # not actually deleted

    def test_returns_empty_when_nothing_to_rotate(self, tmp_path):
        new_file = tmp_path / "claims_claims_20991231_020000.dump"
        new_file.write_bytes(b"new")
        deleted = bkp.rotate_old_backups(tmp_path, retention_days=14)
        assert deleted == []


# ---------------------------------------------------------------------------
# backup_postgres.upload_to_s3
# ---------------------------------------------------------------------------


class TestUploadToS3:
    def test_dry_run_skips_upload(self, tmp_path):
        local = tmp_path / "claims_20240101_020000.dump"
        local.write_bytes(b"PGDMP")
        uri = bkp.upload_to_s3(local, "my-bucket", "postgres-backups", None, dry_run=True)
        assert uri == "s3://my-bucket/postgres-backups/claims_20240101_020000.dump"

    def test_missing_boto3_raises_runtime_error(self, tmp_path, monkeypatch):
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "boto3":
                raise ImportError("No module named 'boto3'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        local = tmp_path / "test.dump"
        local.write_bytes(b"test")
        with pytest.raises(RuntimeError, match="boto3"):
            bkp.upload_to_s3(local, "bucket", "prefix", None, dry_run=False)

    def test_s3_uri_format(self, tmp_path):
        local = tmp_path / "claims_20240101_020000.dump"
        local.write_bytes(b"PGDMP")
        uri = bkp.upload_to_s3(local, "my-bucket", "backups/pg", None, dry_run=True)
        assert uri.startswith("s3://my-bucket/")
        assert local.name in uri


# ---------------------------------------------------------------------------
# backup_postgres main() integration
# ---------------------------------------------------------------------------


class TestBackupMain:
    def test_dry_run_returns_0(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql://claims:secret@localhost/claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))

        with patch("shutil.which", return_value="/usr/bin/pg_dump"):
            rc = bkp.main(["--dry-run"])
        assert rc == 0

    def test_missing_database_url_returns_1(self, monkeypatch, tmp_path):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        rc = bkp.main(["--pg-url", ""])
        assert rc == 1

    def test_missing_pg_dump_returns_1(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql://claims:secret@localhost/claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        with patch("shutil.which", return_value=None):
            rc = bkp.main([])
        assert rc == 1

    def test_pg_dump_failure_returns_2(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql://claims:secret@localhost/claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "connection refused"

        with patch("shutil.which", return_value="/usr/bin/pg_dump"):
            with patch("subprocess.run", return_value=mock_result):
                rc = bkp.main([])
        assert rc == 2

    def test_malformed_pg_url_returns_1(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql:///claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        with patch("shutil.which", return_value="/usr/bin/pg_dump"):
            rc = bkp.main([])
        assert rc == 1


# ---------------------------------------------------------------------------
# restore_postgres.run_schema_upgrade
# ---------------------------------------------------------------------------


class TestRunSchemaUpgrade:
    def test_passes_database_url_to_subprocess_env(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://wrong-host/wrongdb")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("shutil.which", return_value="/usr/bin/alembic"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                rst.run_schema_upgrade(database_url="postgresql://restore-target/db")

        env = mock_run.call_args.kwargs["env"]
        assert env["DATABASE_URL"] == "postgresql://restore-target/db"


# ---------------------------------------------------------------------------
# restore_postgres helpers
# ---------------------------------------------------------------------------


class TestListBackups:
    def test_returns_newest_first(self, tmp_path):
        import time

        f1 = tmp_path / "claims_claims_20240101_020000.dump"
        f1.write_bytes(b"old")
        time.sleep(0.05)
        f2 = tmp_path / "claims_claims_20240201_020000.dump"
        f2.write_bytes(b"new")

        result = rst.list_backups(tmp_path)
        assert result[0] == f2
        assert result[1] == f1

    def test_empty_directory(self, tmp_path):
        assert rst.list_backups(tmp_path) == []

    def test_returns_both_extensions(self, tmp_path):
        (tmp_path / "claims_a_20240101_020000.dump").write_bytes(b"d")
        (tmp_path / "claims_b_20240201_020000.sql").write_bytes(b"s")
        result = rst.list_backups(tmp_path)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# restore_postgres.run_pg_restore
# ---------------------------------------------------------------------------


class TestRunPgRestore:
    def test_uses_pg_restore_for_dump_files(self, tmp_path):
        dump_file = tmp_path / "claims_20240101_020000.dump"
        dump_file.write_bytes(b"PGDMP")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            rst.run_pg_restore(
                "postgresql://localhost/claims",
                dump_file,
                "/usr/bin/pg_restore",
                "/usr/bin/psql",
            )
        cmd = mock_run.call_args[0][0]
        kwargs = mock_run.call_args.kwargs
        assert cmd[0] == "/usr/bin/pg_restore"
        assert str(dump_file) in cmd
        assert "-h" in cmd
        assert "timeout" in kwargs

    def test_uses_psql_for_sql_files(self, tmp_path):
        sql_file = tmp_path / "claims_20240101_020000.sql"
        sql_file.write_text("-- plain sql backup")

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            rst.run_pg_restore(
                "postgresql://localhost/claims",
                sql_file,
                "/usr/bin/pg_restore",
                "/usr/bin/psql",
            )
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "/usr/bin/psql"
        assert "-v" in cmd
        assert "ON_ERROR_STOP=1" in cmd
        assert "-f" in cmd
        assert str(sql_file) in cmd

    def test_dry_run_skips_subprocess(self, tmp_path):
        dump_file = tmp_path / "test.dump"
        dump_file.write_bytes(b"PGDMP")
        with patch("subprocess.run") as mock_run:
            rst.run_pg_restore(
                "postgresql://localhost/claims",
                dump_file,
                "pg_restore",
                "psql",
                dry_run=True,
            )
        mock_run.assert_not_called()

    def test_raises_on_nonzero_exit(self, tmp_path):
        dump_file = tmp_path / "test.dump"
        dump_file.write_bytes(b"PGDMP")
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"
        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(RuntimeError, match="1"):
                rst.run_pg_restore("postgresql://localhost/claims", dump_file, "pg_restore", "psql")


# ---------------------------------------------------------------------------
# restore_postgres main() integration
# ---------------------------------------------------------------------------


class TestRestoreMain:
    def test_list_mode_returns_0_empty_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        rc = rst.main(["--list"])
        assert rc == 0

    def test_list_mode_missing_dir_returns_1(self, monkeypatch, tmp_path):
        missing_dir = tmp_path / "nonexistent"
        monkeypatch.setenv("BACKUP_DIR", str(missing_dir))
        rc = rst.main(["--list"])
        assert rc == 1

    def test_no_backup_file_returns_1(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        rc = rst.main([])
        assert rc == 1

    def test_missing_backup_file_returns_1(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        with patch("shutil.which", return_value="/usr/bin/pg_restore"):
            rc = rst.main(["nonexistent.dump"])
        assert rc == 1

    def test_dry_run_returns_0(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))

        dump_file = tmp_path / "claims_claims_20240101_020000.dump"
        dump_file.write_bytes(b"PGDMP")

        with patch("shutil.which", return_value="/usr/bin/pg_restore"):
            rc = rst.main(["--dry-run", str(dump_file)])
        assert rc == 0

    def test_restore_failure_returns_2(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))

        dump_file = tmp_path / "claims_claims_20240101_020000.dump"
        dump_file.write_bytes(b"PGDMP")

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "connection refused"

        with patch("shutil.which", return_value="/usr/bin/pg_restore"):
            with patch("subprocess.run", return_value=mock_result):
                rc = rst.main([str(dump_file), "--no-schema-upgrade"])
        assert rc == 2

    def test_malformed_pg_url_returns_1(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DATABASE_URL", "postgresql:///claims")
        monkeypatch.setenv("BACKUP_DIR", str(tmp_path))
        dump_file = tmp_path / "claims_claims_20240101_020000.dump"
        dump_file.write_bytes(b"PGDMP")
        with patch("shutil.which", return_value="/usr/bin/pg_restore"):
            rc = rst.main([str(dump_file), "--no-schema-upgrade"])
        assert rc == 1


# ---------------------------------------------------------------------------
# BackupConfig settings
# ---------------------------------------------------------------------------


class TestBackupConfig:
    def test_defaults(self):
        from claim_agent.config.settings_model import BackupConfig

        cfg = BackupConfig()
        assert cfg.enabled is False
        assert cfg.backup_dir == "data/backups"
        assert cfg.retention_days == 14
        assert cfg.s3_bucket == ""
        assert cfg.s3_prefix == "postgres-backups"
        assert cfg.s3_endpoint is None
        assert cfg.compress is True

    def test_enabled_via_env(self, monkeypatch):
        monkeypatch.setenv("BACKUP_ENABLED", "true")
        from claim_agent.config.settings_model import BackupConfig

        cfg = BackupConfig()
        assert cfg.enabled is True

    def test_retention_days_via_env(self, monkeypatch):
        monkeypatch.setenv("BACKUP_RETENTION_DAYS", "30")
        from claim_agent.config.settings_model import BackupConfig

        cfg = BackupConfig()
        assert cfg.retention_days == 30

    def test_s3_endpoint_empty_becomes_none(self, monkeypatch):
        monkeypatch.setenv("BACKUP_S3_ENDPOINT", "")
        from claim_agent.config.settings_model import BackupConfig

        cfg = BackupConfig()
        assert cfg.s3_endpoint is None

    def test_s3_endpoint_set(self, monkeypatch):
        monkeypatch.setenv("BACKUP_S3_ENDPOINT", "http://minio:9000")
        from claim_agent.config.settings_model import BackupConfig

        cfg = BackupConfig()
        assert cfg.s3_endpoint == "http://minio:9000"

    def test_pg_psql_path_default(self):
        from claim_agent.config.settings_model import BackupConfig

        cfg = BackupConfig()
        assert cfg.pg_psql_path == "psql"

    def test_pg_psql_path_via_env(self, monkeypatch):
        monkeypatch.setenv("BACKUP_PG_PSQL_PATH", "/usr/bin/psql")
        from claim_agent.config.settings_model import BackupConfig

        cfg = BackupConfig()
        assert cfg.pg_psql_path == "/usr/bin/psql"

    def test_backup_on_settings(self):
        from claim_agent.config.settings_model import Settings

        s = Settings()
        assert hasattr(s, "backup")
        assert s.backup.retention_days == 14
