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
                  backup file produced by backup_postgres.py.  Pass ``-`` to
                  list available backups from BACKUP_DIR without restoring.

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

Restore procedure (complete step-by-step)
------------------------------------------
The following steps constitute the tested restore procedure.  After any real
disaster-recovery event, record completion of each step in an incident
postmortem.

1.  **Stop the application** to prevent writes during restore::

        claim-agent serve --stop   # or: docker compose stop claim-agent

2.  **Choose a backup file**::

        python scripts/restore_postgres.py --list

3.  **Create a pre-restore snapshot** (RDS only, optional but recommended)::

        aws rds create-db-snapshot \\
          --db-instance-identifier claims-db \\
          --db-snapshot-identifier claims-pre-restore-$(date +%Y%m%d)

4.  **Drop and recreate the target database** to start from a clean state::

        psql -U postgres -c "DROP DATABASE IF EXISTS claims;"
        psql -U postgres -c "CREATE DATABASE claims OWNER claims;"

5.  **Run this script**::

        DATABASE_URL=postgresql://claims:secret@localhost:5432/claims \\
          python scripts/restore_postgres.py /path/to/claims_YYYYMMDD_HHMMSS.dump

6.  **Verify row counts** match expectations (e.g., compare against the backup
    metadata or a pre-failure snapshot).

7.  **Restart the application**::

        claim-agent serve --workers 4

8.  **Run smoke tests**::

        pytest tests/ -m smoke -v

RTO / RPO targets
-----------------
See ``scripts/backup_postgres.py`` and ``docs/database.md`` for the full
RTO/RPO table.  In summary:

    RPO ≤ 24 hours  (daily backups; PITR WAL archiving reduces to minutes)
    RTO ≤ 4 hours   (pg_restore + alembic upgrade head + smoke tests)
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("restore_postgres")

_DUMP_PREFIX = "claims_"
_DUMP_EXTS = (".dump", ".sql")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


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


def _resolve_pg_url(cli_url: str | None) -> str:
    url = cli_url or os.environ.get("DATABASE_URL", "")
    if not url or not url.strip():
        raise SystemExit("ERROR: No PostgreSQL URL provided. Set DATABASE_URL or pass --pg-url.")
    url = url.strip()
    if not url.startswith("postgresql://") and not url.startswith("postgres://"):
        raise SystemExit(f"ERROR: URL does not look like a PostgreSQL URL: {url!r}")
    return url


def _resolve_backup_dir(cli_dir: str | None) -> Path:
    env_dir = os.environ.get("BACKUP_DIR", "").strip()
    raw = cli_dir or env_dir or "data/backups"
    path = Path(raw)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent / path
    return path


def _resolve_binary(name: str, cli_path: str | None, env_var: str) -> str:
    raw = cli_path or os.environ.get(env_var, "").strip() or name
    found = shutil.which(raw)
    if found is None:
        raise SystemExit(f"ERROR: {name} binary not found at {raw!r}. Install postgresql-client.")
    return found


def _mask_url_password(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(parsed.password, "***", 1)
    except Exception:
        pass
    return url


def _resolve_backup_file(backup_file: str, backup_dir: Path) -> Path:
    path = Path(backup_file)
    if path.exists():
        return path.resolve()
    # Try relative to backup_dir
    candidate = backup_dir / backup_file
    if candidate.exists():
        return candidate.resolve()
    raise SystemExit(f"ERROR: Backup file not found: {backup_file!r}")


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------


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
) -> None:
    """Restore *backup_path* into the database specified by *pg_url*.

    For ``.dump`` (custom format) files this calls ``pg_restore``.
    For ``.sql`` (plain) files this calls ``psql`` (pipes stdin).

    Args:
        pg_url: Full PostgreSQL connection URL.
        backup_path: Path to the dump file.
        pg_restore_bin: Resolved path to pg_restore.
        pg_psql_bin: Resolved path to psql.
        dry_run: Log commands without executing.
    """
    safe_url = _mask_url_password(pg_url)

    if backup_path.suffix == ".sql":
        cmd = [pg_psql_bin, "--no-password", pg_url, "-f", str(backup_path)]
        safe_cmd = [pg_psql_bin, "--no-password", safe_url, "-f", str(backup_path)]
    else:
        cmd = [
            pg_restore_bin,
            "--no-password",
            "--clean",
            "--if-exists",
            "--exit-on-error",
            "-d",
            pg_url,
            str(backup_path),
        ]
        safe_cmd = cmd[:-2] + [safe_url, str(backup_path)]

    logger.info("Running: %s", " ".join(safe_cmd))

    if dry_run:
        logger.info("[dry-run] Skipping actual restore execution.")
        return

    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        logger.error("Restore failed (exit %d):\n%s", result.returncode, result.stderr)
        raise RuntimeError(f"Restore exited with code {result.returncode}")
    logger.info("Restore completed: %s", backup_path.name)
    if result.stderr:
        logger.debug("restore stderr: %s", result.stderr.strip())


def run_schema_upgrade(dry_run: bool = False) -> None:
    """Run ``alembic upgrade head`` to apply any pending migrations.

    Args:
        dry_run: Log the command without running it.
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

    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        logger.error("alembic upgrade head failed (exit %d):\n%s", result.returncode, result.stderr)
        raise RuntimeError("alembic upgrade head failed")
    logger.info("Schema upgrade complete.")
    if result.stdout:
        logger.debug("alembic output: %s", result.stdout.strip())


def run_smoke_test(pg_url: str, pg_psql_bin: str, dry_run: bool = False) -> None:
    """Run a minimal SQL query to verify the restored database is accessible.

    Executes ``SELECT count(*) FROM claims`` and logs the result.

    Args:
        pg_url: Full PostgreSQL connection URL.
        pg_psql_bin: Resolved path to psql.
        dry_run: Log the command without running it.
    """
    safe_url = _mask_url_password(pg_url)
    cmd = [pg_psql_bin, "--no-password", "-t", "-c", "SELECT count(*) FROM claims;", pg_url]
    safe_cmd = cmd[:-2] + [safe_url]
    logger.info("Running smoke test: %s", " ".join(safe_cmd))

    if dry_run:
        logger.info("[dry-run] Skipping smoke test.")
        return

    result = subprocess.run(cmd, capture_output=True, text=True)  # noqa: S603
    if result.returncode != 0:
        logger.error("Smoke test failed (exit %d):\n%s", result.returncode, result.stderr)
        raise RuntimeError("Smoke test failed")
    count = result.stdout.strip()
    logger.info("Smoke test passed — claims table row count: %s", count)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _configure_logging(args.verbose)

    backup_dir = _resolve_backup_dir(args.backup_dir)

    # ------------------------------------------------------------------
    # List mode
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Resolve inputs
    # ------------------------------------------------------------------
    if not args.backup_file:
        logger.error("No backup file specified. Use --list to see available backups.")
        return 1

    try:
        pg_url = _resolve_pg_url(args.pg_url)
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

    safe_url = _mask_url_password(pg_url)
    logger.info("Restore configuration:")
    logger.info("  backup_file   : %s", backup_path)
    logger.info("  pg_url        : %s", safe_url)
    logger.info("  schema_upgrade: %s", not args.no_schema_upgrade)

    if args.dry_run:
        logger.info("[dry-run] Configuration validated. No restore will be executed.")
        return 0

    # ------------------------------------------------------------------
    # Perform restore
    # ------------------------------------------------------------------
    try:
        run_pg_restore(pg_url, backup_path, pg_restore_bin, pg_psql_bin)
    except RuntimeError as exc:
        logger.error("Restore failed: %s", exc)
        return 2

    # ------------------------------------------------------------------
    # Apply pending migrations
    # ------------------------------------------------------------------
    if not args.no_schema_upgrade:
        try:
            run_schema_upgrade()
        except RuntimeError as exc:
            logger.error("Schema upgrade failed: %s", exc)
            return 2

    # ------------------------------------------------------------------
    # Smoke test
    # ------------------------------------------------------------------
    try:
        run_smoke_test(pg_url, pg_psql_bin)
    except RuntimeError as exc:
        logger.error("Smoke test failed after restore: %s", exc)
        return 2

    logger.info("Restore procedure complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
