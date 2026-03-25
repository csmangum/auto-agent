"""PostgreSQL restore script.

Restores the claims PostgreSQL database from a pg_dump backup file created by
``scripts/backup_postgres.py``.  After restoring the raw data the script
automatically runs ``alembic upgrade head`` to ensure the schema is at the
expected revision, then performs a basic smoke-test query to verify the
restore was successful.

Usage
-----
    python scripts/restore_postgres.py [OPTIONS] <backup-file>

Positional argument
-------------------
    backup-file   Path to a ``.dump`` (custom compressed) or ``.sql`` (plain)
                  backup file produced by backup_postgres.py.  Omit when using --list.

Options
-------
    --pg-url URL          PostgreSQL connection URL.
                          Default: DATABASE_URL env var.
    --backup-dir DIR      Directory to search for backup files when listing
                          or when backup-file is a bare filename.
                          Default: BACKUP_DIR env var, then ``data/backups``.
    --pg-restore-path PATH  Path to pg_restore binary (default: pg_restore).
    --pg-psql-path PATH   Path to psql binary (default: psql).
    --no-schema-upgrade   Skip running ``alembic upgrade head`` after restore.
    --list                List available backup files and exit.
    --dry-run             Print what would be done without executing.
    --verbose             Enable debug logging.

Exit codes
----------
    0   Restore completed (and schema upgraded) successfully.
    1   Configuration or argument error.
    2   pg_restore, schema upgrade, or smoke-test failure.

Subprocess timeouts (env): ``BACKUP_PG_RESTORE_TIMEOUT``, ``BACKUP_PG_SMOKE_TIMEOUT``,
``BACKUP_ALEMBIC_TIMEOUT`` (defaults 3600, 60, 600 seconds).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from _backup_common import (
    PostgresConnParams,
    alembic_timeout_seconds,
    configure_logging,
    mask_url_password,
    parse_postgres_url,
    pg_subprocess_env,
    resolve_backup_dir,
    resolve_pg_url,
    restore_timeout_seconds,
    smoke_timeout_seconds,
)

logger = logging.getLogger("restore_postgres")

_DUMP_PREFIX = "claims_"
_DUMP_EXTS = (".dump", ".sql")

_SCRIPTS_PARENT = Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore the claims PostgreSQL database from a pg_dump backup.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "backup_file",
        nargs="?",
        default=None,
        help="Path to backup file (.dump or .sql). Omit when using --list.",
    )
    parser.add_argument("--pg-url", default=None, help="PostgreSQL connection URL (default: DATABASE_URL).")
    parser.add_argument("--backup-dir", default=None, help="Directory to search for backups.")
    parser.add_argument("--pg-restore-path", default=None, help="Path to pg_restore binary.")
    parser.add_argument("--pg-psql-path", default=None, help="Path to psql binary.")
    parser.add_argument("--no-schema-upgrade", action="store_true", help="Skip alembic upgrade head after restore.")
    parser.add_argument("--list", action="store_true", help="List available backup files and exit.")
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args(argv)


def _resolve_backup_dir(cli_dir: str | None) -> Path:
    return resolve_backup_dir(cli_dir, _SCRIPTS_PARENT)


def _resolve_binary(name: str, cli_path: str | None, env_var: str) -> str:
    raw = cli_path or os.environ.get(env_var, "").strip() or name
    found = shutil.which(raw)
    if found is None:
        raise SystemExit(f"ERROR: {name} binary not found at {raw!r}. Install postgresql-client.")
    return found


def _resolve_backup_file(backup_file: str, backup_dir: Path) -> Path:
    path = Path(backup_file)
    if path.exists():
        return path.resolve()
    candidate = backup_dir / backup_file
    if candidate.exists():
        return candidate.resolve()
    raise SystemExit(f"ERROR: Backup file not found: {backup_file!r}")


def _psql_base_cmd(pg_psql_bin: str, params: PostgresConnParams) -> list[str]:
    cmd: list[str] = [pg_psql_bin, "--no-password"]
    if params.user:
        cmd.extend(["-U", params.user])
    cmd.extend(["-h", params.host, "-p", str(params.port), "-d", params.dbname])
    return cmd


def _pg_restore_base_cmd(pg_restore_bin: str, params: PostgresConnParams) -> list[str]:
    cmd: list[str] = [
        pg_restore_bin,
        "--no-password",
        "--clean",
        "--if-exists",
        "--exit-on-error",
    ]
    if params.user:
        cmd.extend(["-U", params.user])
    cmd.extend(["-h", params.host, "-p", str(params.port), "-d", params.dbname])
    return cmd


def list_backups(backup_dir: Path) -> list[Path]:
    """Return backup files in *backup_dir*, newest first."""
    files: list[Path] = []
    for ext in _DUMP_EXTS:
        files.extend(backup_dir.glob(f"{_DUMP_PREFIX}*{ext}"))
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)


def run_pg_restore(
    pg_url: str,
    backup_path: Path,
    pg_restore_bin: str,
    pg_psql_bin: str,
    dry_run: bool = False,
    timeout: int | None = None,
) -> None:
    """Restore *backup_path* using discrete connection flags and ``PGPASSWORD``."""
    params = parse_postgres_url(pg_url)
    env = pg_subprocess_env(params.password)
    t = timeout if timeout is not None else restore_timeout_seconds()

    if backup_path.suffix == ".sql":
        cmd = _psql_base_cmd(pg_psql_bin, params) + [
            "-v",
            "ON_ERROR_STOP=1",
            "-f",
            str(backup_path),
        ]
    else:
        cmd = _pg_restore_base_cmd(pg_restore_bin, params) + [str(backup_path)]

    logger.info("Running: %s", " ".join(cmd))

    if dry_run:
        logger.info("[dry-run] Skipping actual restore execution.")
        return

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=t)  # noqa: S603
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"restore timed out after {t}s") from exc
    if result.returncode != 0:
        logger.error("Restore failed (exit %d):\n%s", result.returncode, result.stderr)
        raise RuntimeError(f"Restore exited with code {result.returncode}")
    logger.info("Restore completed: %s", backup_path.name)
    if result.stderr:
        logger.debug("restore stderr: %s", result.stderr.strip())


def run_schema_upgrade(
    dry_run: bool = False,
    timeout: int | None = None,
    database_url: str | None = None,
) -> None:
    """Run ``alembic upgrade head`` to apply any pending migrations.

    When *database_url* is set, it is passed to the subprocess as ``DATABASE_URL``
    so Alembic targets the same database as the restore (e.g. when using
    ``--pg-url`` without exporting ``DATABASE_URL`` in the shell).
    """
    alembic_bin = shutil.which("alembic")
    if alembic_bin is None:
        logger.warning("alembic not found on PATH; skipping schema upgrade.")
        return

    cmd = [alembic_bin, "upgrade", "head"]
    logger.info("Running schema upgrade: %s", " ".join(cmd))
    if dry_run:
        logger.info("[dry-run] Skipping alembic upgrade head.")
        return

    env = os.environ.copy()
    if database_url is not None:
        env["DATABASE_URL"] = database_url

    t = timeout if timeout is not None else alembic_timeout_seconds()
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            timeout=t,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"alembic upgrade head timed out after {t}s") from exc
    if result.returncode != 0:
        logger.error("alembic upgrade head failed (exit %d):\n%s", result.returncode, result.stderr)
        raise RuntimeError("alembic upgrade head failed")
    logger.info("Schema upgrade complete.")
    if result.stdout:
        logger.debug("alembic output: %s", result.stdout.strip())


def run_smoke_test(pg_url: str, pg_psql_bin: str, dry_run: bool = False, timeout: int | None = None) -> None:
    """Run ``SELECT count(*) FROM claims`` via psql (no password on argv)."""
    params = parse_postgres_url(pg_url)
    env = pg_subprocess_env(params.password)
    cmd = _psql_base_cmd(pg_psql_bin, params) + ["-t", "-c", "SELECT count(*) FROM claims;"]
    logger.info("Running smoke test: %s", " ".join(cmd))

    if dry_run:
        logger.info("[dry-run] Skipping smoke test.")
        return

    t = timeout if timeout is not None else smoke_timeout_seconds()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=t)  # noqa: S603
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"smoke test timed out after {t}s") from exc
    if result.returncode != 0:
        logger.error("Smoke test failed (exit %d):\n%s", result.returncode, result.stderr)
        raise RuntimeError("Smoke test failed")
    count = result.stdout.strip()
    logger.info("Smoke test passed — claims table row count: %s", count)


_mask_url_password = mask_url_password


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(args.verbose, "restore_postgres")

    backup_dir = _resolve_backup_dir(args.backup_dir)

    if args.list:
        if not backup_dir.exists():
            logger.error("Backup directory does not exist: %s", backup_dir)
            return 1
        files = list_backups(backup_dir)
        if not files:
            print(f"No backup files found in {backup_dir}")
        else:
            print(f"Available backups in {backup_dir} (newest first):")
            for f in files:
                size_mb = f.stat().st_size / (1024 * 1024)
                print(f"  {f.name}  ({size_mb:.2f} MB)")
        return 0

    if not args.backup_file:
        logger.error("No backup file specified. Use --list to see available backups.")
        return 1

    try:
        pg_url = resolve_pg_url(args.pg_url)
    except SystemExit as exc:
        logger.error("%s", exc)
        return 1

    try:
        pg_restore_bin = _resolve_binary("pg_restore", args.pg_restore_path, "BACKUP_PG_RESTORE_PATH")
        pg_psql_bin = _resolve_binary("psql", args.pg_psql_path, "BACKUP_PG_PSQL_PATH")
    except SystemExit as exc:
        logger.error("%s", exc)
        return 1

    try:
        backup_path = _resolve_backup_file(args.backup_file, backup_dir)
    except SystemExit as exc:
        logger.error("%s", exc)
        return 1

    safe_url = mask_url_password(pg_url)
    logger.info("Restore configuration:")
    logger.info("  backup_file   : %s", backup_path)
    logger.info("  pg_url        : %s", safe_url)
    logger.info("  schema_upgrade: %s", not args.no_schema_upgrade)

    if args.dry_run:
        logger.info("[dry-run] Configuration validated. No restore will be executed.")
        return 0

    try:
        run_pg_restore(pg_url, backup_path, pg_restore_bin, pg_psql_bin)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return 1
    except RuntimeError as exc:
        logger.error("Restore failed: %s", exc)
        return 2

    if not args.no_schema_upgrade:
        try:
            run_schema_upgrade(database_url=pg_url)
        except RuntimeError as exc:
            logger.error("Schema upgrade failed: %s", exc)
            return 2

    try:
        run_smoke_test(pg_url, pg_psql_bin)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return 1
    except RuntimeError as exc:
        logger.error("Smoke test failed after restore: %s", exc)
        return 2

    logger.info("Restore procedure complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
