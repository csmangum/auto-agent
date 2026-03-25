"""Automated PostgreSQL backup script.

Runs ``pg_dump`` against the configured PostgreSQL database, writes the dump
to a local directory, rotates old files beyond the retention window, and
optionally uploads the new backup to S3.

Usage
-----
    python scripts/backup_postgres.py [OPTIONS]

Options
-------
    --pg-url URL          PostgreSQL connection URL.
                          Default: DATABASE_URL env var.
    --backup-dir DIR      Local directory for dump files.
                          Default: BACKUP_DIR env var, then ``data/backups``.
    --retention-days N    Delete local dumps older than N days (default: 14).
    --s3-bucket BUCKET    S3 bucket for upload. Overrides BACKUP_S3_BUCKET.
    --s3-prefix PREFIX    Key prefix inside the S3 bucket (default: postgres-backups).
    --s3-endpoint URL     S3-compatible endpoint URL (e.g. MinIO). Overrides BACKUP_S3_ENDPOINT.
    --no-compress         Write plain SQL instead of custom compressed format.
    --pg-dump-path PATH   Path to pg_dump binary (default: pg_dump on PATH).
    --dry-run             Validate configuration without creating a backup.
    --verbose             Enable debug logging.

Exit codes
----------
    0   Backup completed successfully.
    1   Configuration error (missing DATABASE_URL, pg_dump not found, etc.).
    2   Backup or upload failed.

Scheduling
----------
Add a cron entry (or systemd timer) to run this script regularly.  Example
cron job that runs at 02:00 UTC every day and writes to /var/backups/claims::

    0 2 * * * postgres \\
        DATABASE_URL=postgresql://claims:secret@localhost:5432/claims \\
        python /app/scripts/backup_postgres.py \\
        --backup-dir /var/backups/claims \\
        --retention-days 14

For Docker Compose deployments, consider running this script in a dedicated
``backup`` service that shares the same environment variables as the main
``claim-agent`` service.

RTO / RPO targets
-----------------
With daily full backups and 14-day retention:

+---------------------------+------------------+------------------------------------------+
| Scenario                  | Target           | How achieved                             |
+===========================+==================+==========================================+
| Recovery Point Objective  | ≤ 24 hours       | Daily pg_dump; enable WAL archiving for  |
| (RPO)                     |                  | PITR down to minutes.                    |
+---------------------------+------------------+------------------------------------------+
| Recovery Time Objective   | ≤ 4 hours        | pg_restore from latest dump + alembic    |
| (RTO)                     |                  | upgrade head (schema) + smoke tests.     |
+---------------------------+------------------+------------------------------------------+

See ``docs/database.md`` for the full restore procedure and RTO/RPO rationale.

Restore
-------
See ``scripts/restore_postgres.py`` for the guided restore script, or run
pg_restore manually::

    pg_restore -U claims -d claims /path/to/claims_YYYYMMDD_HHMMSS.dump

Always run ``alembic upgrade head`` after restoring to ensure the schema is
at the expected revision.

Subprocess timeouts (env): ``BACKUP_PG_DUMP_TIMEOUT`` (default 3600 seconds).
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from _backup_common import (
    PostgresConnParams,
    configure_logging,
    dump_timeout_seconds,
    mask_url_password,
    parse_postgres_url,
    pg_subprocess_env,
    resolve_backup_dir,
    resolve_pg_url,
)

logger = logging.getLogger("backup_postgres")

_DUMP_EXT_COMPRESSED = ".dump"
_DUMP_EXT_PLAIN = ".sql"
_DUMP_PREFIX = "claims_"

_SCRIPTS_PARENT = Path(__file__).resolve().parent.parent


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backup the claims PostgreSQL database via pg_dump.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--pg-url", default=None, help="PostgreSQL connection URL (default: DATABASE_URL env var).")
    parser.add_argument("--backup-dir", default=None, help="Local directory for dump files (default: data/backups).")
    parser.add_argument("--retention-days", type=int, default=None, help="Days to keep local backups (default: 14).")
    parser.add_argument("--s3-bucket", default=None, help="S3 bucket to upload backup to.")
    parser.add_argument("--s3-prefix", default=None, help="S3 key prefix (default: postgres-backups).")
    parser.add_argument("--s3-endpoint", default=None, help="S3-compatible endpoint URL.")
    parser.add_argument("--no-compress", action="store_true", help="Write plain SQL instead of custom compressed format.")
    parser.add_argument("--pg-dump-path", default=None, help="Path to pg_dump binary.")
    parser.add_argument("--dry-run", action="store_true", help="Validate configuration without creating a backup.")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging.")
    return parser.parse_args(argv)


def _resolve_backup_dir(cli_dir: str | None) -> Path:
    return resolve_backup_dir(cli_dir, _SCRIPTS_PARENT)


def _resolve_retention_days(cli_days: int | None) -> int:
    if cli_days is not None:
        days = cli_days
    else:
        env_val = os.environ.get("BACKUP_RETENTION_DAYS", "").strip()
        if env_val:
            try:
                days = int(env_val)
            except ValueError:
                logger.warning("BACKUP_RETENTION_DAYS is not an integer (%r); using default 14.", env_val)
                return 14
        else:
            return 14
    if days < 1:
        logger.warning("Retention days must be >= 1 (got %d); using default 14.", days)
        return 14
    return days


def _resolve_pg_dump_path(cli_path: str | None) -> str:
    raw = cli_path or os.environ.get("BACKUP_PG_DUMP_PATH", "").strip() or "pg_dump"
    found = shutil.which(raw)
    if found is None:
        raise SystemExit(f"ERROR: pg_dump binary not found at {raw!r}. Install postgresql-client.")
    return found


def _db_name_from_url(pg_url: str) -> str:
    """Extract the database name portion of a PostgreSQL URL for use in the filename."""
    try:
        parsed = urlparse(pg_url)
        db = parsed.path.lstrip("/")
        return db if db else "claims"
    except Exception:
        return "claims"


def _backup_filename(db_name: str, compress: bool) -> str:
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    ext = _DUMP_EXT_COMPRESSED if compress else _DUMP_EXT_PLAIN
    return f"{_DUMP_PREFIX}{db_name}_{ts}{ext}"


def _pg_dump_command(pg_dump_bin: str, params: PostgresConnParams, fmt_flag: str, output_path: Path) -> list[str]:
    cmd: list[str] = [pg_dump_bin, fmt_flag, "--no-password"]
    if params.user:
        cmd.extend(["-U", params.user])
    cmd.extend(
        [
            "-h",
            params.host,
            "-p",
            str(params.port),
            "-d",
            params.dbname,
            "-f",
            str(output_path),
        ]
    )
    return cmd


def run_pg_dump(
    pg_url: str,
    output_path: Path,
    pg_dump_bin: str,
    compress: bool,
    dry_run: bool = False,
    timeout: int | None = None,
) -> None:
    """Run pg_dump and write output to *output_path*.

    Uses discrete ``-h/-p/-U/-d`` flags and ``PGPASSWORD`` in the subprocess
    environment so credentials do not appear in ``/proc/*/cmdline``.
    """
    params = parse_postgres_url(pg_url)
    fmt_flag = "-Fc" if compress else "-Fp"
    cmd = _pg_dump_command(pg_dump_bin, params, fmt_flag, output_path)
    safe_cmd = " ".join(cmd)
    logger.info("Running: %s", safe_cmd)

    if dry_run:
        logger.info("[dry-run] Skipping actual pg_dump execution.")
        return

    env = pg_subprocess_env(params.password)
    t = timeout if timeout is not None else dump_timeout_seconds()
    start = time.monotonic()
    try:
        result = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            text=True,
            env=env,
            timeout=t,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"pg_dump timed out after {t}s") from exc
    elapsed = time.monotonic() - start

    if result.returncode != 0:
        logger.error("pg_dump failed (exit %d):\n%s", result.returncode, result.stderr)
        raise RuntimeError(f"pg_dump exited with code {result.returncode}")

    size_mb = output_path.stat().st_size / (1024 * 1024) if output_path.exists() else 0
    logger.info("pg_dump completed in %.1fs — %s (%.2f MB)", elapsed, output_path.name, size_mb)
    if result.stderr:
        logger.debug("pg_dump stderr: %s", result.stderr.strip())


def rotate_old_backups(backup_dir: Path, retention_days: int, dry_run: bool = False) -> list[Path]:
    """Delete dump files in *backup_dir* older than *retention_days*."""
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=retention_days)
    deleted: list[Path] = []

    for ext in (_DUMP_EXT_COMPRESSED, _DUMP_EXT_PLAIN):
        for f in backup_dir.glob(f"{_DUMP_PREFIX}*{ext}"):
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                logger.info(
                    "%s %s (mtime %s, older than %d days)",
                    "[dry-run] would delete" if dry_run else "Deleting",
                    f.name,
                    mtime.date(),
                    retention_days,
                )
                if not dry_run:
                    f.unlink()
                deleted.append(f)

    return deleted


def upload_to_s3(
    local_path: Path,
    s3_bucket: str,
    s3_prefix: str,
    s3_endpoint: str | None,
    dry_run: bool = False,
) -> str:
    """Upload *local_path* to S3 and return the S3 URI."""
    key = f"{s3_prefix.rstrip('/')}/{local_path.name}"
    s3_uri = f"s3://{s3_bucket}/{key}"

    if dry_run:
        logger.info("[dry-run] Would upload %s → %s", local_path.name, s3_uri)
        return s3_uri

    try:
        import boto3  # type: ignore[import-untyped]
        from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
    except ImportError:
        raise RuntimeError(
            "boto3 is required for S3 uploads. Install it with: pip install boto3 "
            "or: pip install 'claim-agent[s3]'"
        )

    kwargs: dict[str, object] = {}
    if s3_endpoint:
        kwargs["endpoint_url"] = s3_endpoint

    try:
        client = boto3.client("s3", **kwargs)
        logger.info("Uploading %s → %s", local_path.name, s3_uri)
        client.upload_file(str(local_path), s3_bucket, key)
        logger.info("Upload complete: %s", s3_uri)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"S3 upload failed: {exc}") from exc

    return s3_uri


# Re-export for tests and backward-compatible imports
_mask_url_password = mask_url_password


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    configure_logging(args.verbose, "backup_postgres")

    try:
        pg_url = resolve_pg_url(args.pg_url)
    except SystemExit as exc:
        logger.error("%s", exc)
        return 1

    if args.no_compress:
        compress = False
    else:
        env_val = os.environ.get("BACKUP_COMPRESS", "").strip().lower()
        if env_val in ("false", "0", "no"):
            compress = False
        else:
            compress = True
    backup_dir = _resolve_backup_dir(args.backup_dir)
    retention_days = _resolve_retention_days(args.retention_days)
    s3_bucket = (args.s3_bucket or os.environ.get("BACKUP_S3_BUCKET", "")).strip()
    s3_prefix = (args.s3_prefix or os.environ.get("BACKUP_S3_PREFIX", "postgres-backups")).strip()
    s3_endpoint = args.s3_endpoint or os.environ.get("BACKUP_S3_ENDPOINT", "").strip() or None

    try:
        pg_dump_bin = _resolve_pg_dump_path(args.pg_dump_path)
    except SystemExit as exc:
        logger.error("%s", exc)
        return 1

    safe_url = mask_url_password(pg_url)
    logger.info("Backup configuration:")
    logger.info("  pg_url        : %s", safe_url)
    logger.info("  backup_dir    : %s", backup_dir)
    logger.info("  retention_days: %d", retention_days)
    logger.info("  compress      : %s", compress)
    logger.info("  s3_bucket     : %s", s3_bucket or "(local only)")
    logger.info("  pg_dump_bin   : %s", pg_dump_bin)

    if args.dry_run:
        logger.info("[dry-run] Configuration validated. No backup will be created.")
        return 0

    backup_dir.mkdir(parents=True, exist_ok=True)

    db_name = _db_name_from_url(pg_url)
    filename = _backup_filename(db_name, compress)
    output_path = backup_dir / filename

    try:
        run_pg_dump(pg_url, output_path, pg_dump_bin, compress, dry_run=False)
    except ValueError as exc:
        logger.error("Configuration error: %s", exc)
        return 1
    except RuntimeError as exc:
        logger.error("Backup failed: %s", exc)
        return 2

    if s3_bucket:
        try:
            s3_uri = upload_to_s3(output_path, s3_bucket, s3_prefix, s3_endpoint)
            logger.info("Backup uploaded: %s", s3_uri)
        except RuntimeError as exc:
            logger.error("S3 upload failed: %s", exc)
            return 2

    deleted = rotate_old_backups(backup_dir, retention_days)
    if deleted:
        logger.info("Rotated %d old backup(s).", len(deleted))
    else:
        logger.debug("No old backups to rotate.")

    logger.info("Backup complete: %s", output_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
