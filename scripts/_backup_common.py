"""Shared helpers for PostgreSQL backup and restore scripts.

Keeps configuration resolution, URL masking, and connection parsing in one
place so backup_postgres.py and restore_postgres.py stay in sync.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlunparse, urlparse

# Default subprocess timeouts (overridable via env)
_DEFAULT_DUMP_TIMEOUT = 3600
_DEFAULT_RESTORE_TIMEOUT = 3600
_DEFAULT_SMOKE_TIMEOUT = 60
_DEFAULT_ALEMBIC_TIMEOUT = 600


@dataclass(frozen=True)
class PostgresConnParams:
    """Connection parameters parsed from a postgresql:// URL (no password on CLI)."""

    host: str
    port: int
    user: str | None
    password: str | None
    dbname: str


def configure_logging(verbose: bool, logger_name: str) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )


def mask_url_password(url: str) -> str:
    """Return a log-safe URL with credentials redacted. Fails closed on parse errors."""
    try:
        p = urlparse(url)
        if p.scheme not in ("postgresql", "postgres"):
            return "<redacted>"
        if "@" not in (p.netloc or ""):
            return url
        userinfo, _, hostpart = p.netloc.rpartition("@")
        if ":" in userinfo:
            user, _, _pw = userinfo.partition(":")
            safe_userinfo = f"{user}:***"
        else:
            safe_userinfo = userinfo
        safe_netloc = f"{safe_userinfo}@{hostpart}"
        return urlunparse((p.scheme, safe_netloc, p.path, p.params, p.query, p.fragment))
    except Exception:
        return "<redacted>"


def resolve_pg_url(cli_url: str | None) -> str:
    """Return pg URL from CLI arg or DATABASE_URL env var."""
    url = cli_url or os.environ.get("DATABASE_URL", "")
    if not url or not url.strip():
        raise SystemExit("ERROR: No PostgreSQL URL provided. Set DATABASE_URL or pass --pg-url.")
    url = url.strip()
    if not url.startswith("postgresql://") and not url.startswith("postgres://"):
        raise SystemExit(
            "ERROR: DATABASE_URL does not look like a PostgreSQL URL (expected postgresql:// or postgres://)."
        )
    return url


def resolve_backup_dir(cli_dir: str | None, scripts_parent: Path) -> Path:
    env_dir = os.environ.get("BACKUP_DIR", "").strip()
    raw = cli_dir or env_dir or "data/backups"
    path = Path(raw)
    if not path.is_absolute():
        path = scripts_parent / path
    return path


def parse_postgres_url(url: str) -> PostgresConnParams:
    """Parse a PostgreSQL URL into discrete connection fields (password not for argv)."""
    p = urlparse(url)
    if p.scheme not in ("postgresql", "postgres"):
        raise ValueError("URL must use postgresql:// or postgres:// scheme")
    host = p.hostname
    if not host:
        raise ValueError("PostgreSQL URL must include a host")
    port = p.port if p.port is not None else 5432
    db = (p.path or "").lstrip("/")
    if not db:
        db = "claims"
    return PostgresConnParams(
        host=host,
        port=port,
        user=p.username,
        password=p.password,
        dbname=db,
    )


def pg_subprocess_env(password: str | None) -> dict[str, str]:
    """Copy of process env with PGPASSWORD set when the URL included a password."""
    env = os.environ.copy()
    if password is not None:
        env["PGPASSWORD"] = password
    return env


def dump_timeout_seconds() -> int:
    raw = os.environ.get("BACKUP_PG_DUMP_TIMEOUT", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_DUMP_TIMEOUT


def restore_timeout_seconds() -> int:
    raw = os.environ.get("BACKUP_PG_RESTORE_TIMEOUT", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_RESTORE_TIMEOUT


def smoke_timeout_seconds() -> int:
    raw = os.environ.get("BACKUP_PG_SMOKE_TIMEOUT", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_SMOKE_TIMEOUT


def alembic_timeout_seconds() -> int:
    raw = os.environ.get("BACKUP_ALEMBIC_TIMEOUT", "").strip()
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_ALEMBIC_TIMEOUT
