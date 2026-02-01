"""SQLite connection and schema initialization."""

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

# Tracks which database paths have had schema applied (avoid running on every connection)
_schema_initialized: set[str] = set()
_schema_lock = threading.Lock()

SCHEMA_SQL = """
-- Claims table (main record)
CREATE TABLE IF NOT EXISTS claims (
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

-- Audit log (state changes)
CREATE TABLE IF NOT EXISTS claim_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    details TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);

-- Workflow results (preserves each processing run)
CREATE TABLE IF NOT EXISTS workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    claim_type TEXT,
    router_output TEXT,
    workflow_output TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin);
CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date);
"""


def get_db_path() -> str:
    """Return path to SQLite database from CLAIMS_DB_PATH env or default data/claims.db."""
    path = os.environ.get("CLAIMS_DB_PATH", "data/claims.db")
    return path


def init_db(path: str | None = None) -> None:
    """Create tables if they do not exist."""
    db_path = path or get_db_path()
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    with _schema_lock:
        _schema_initialized.add(db_path)


def _ensure_schema(db_path: str) -> None:
    """Run schema once per path. Thread-safe."""
    with _schema_lock:
        if db_path in _schema_initialized:
            return
    # Run init outside lock to avoid holding it during I/O
    init_db(db_path)


@contextmanager
def get_connection(path: str | None = None):
    """Context manager yielding a database connection. Ensures schema exists once per path."""
    db_path = path or get_db_path()
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    _ensure_schema(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
