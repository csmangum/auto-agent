"""SQLite connection and schema initialization."""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

# Tracks which database paths have had schema applied (avoid running on every connection)
_schema_initialized: set[str] = set()
_schema_lock = threading.RLock()

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
    loss_state TEXT,
    status TEXT DEFAULT 'pending',
    payout_amount REAL,
    reserve_amount REAL,
    attachments TEXT DEFAULT '[]',
    assignee TEXT,
    review_started_at TEXT,
    review_notes TEXT,
    due_at TEXT,
    priority TEXT,
    siu_case_id TEXT,
    archived_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Audit log (state changes). Append-only: no UPDATE or DELETE.
CREATE TABLE IF NOT EXISTS claim_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    action TEXT NOT NULL,
    old_status TEXT,
    new_status TEXT,
    details TEXT,
    actor_id TEXT DEFAULT 'system',
    before_state TEXT,
    after_state TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);

-- Enforce append-only behavior: reject UPDATE/DELETE on claim_audit_log
CREATE TRIGGER IF NOT EXISTS claim_audit_log_prevent_update
BEFORE UPDATE ON claim_audit_log
BEGIN
    SELECT RAISE(ABORT, 'claim_audit_log is append-only: updates are not allowed');
END;

CREATE TRIGGER IF NOT EXISTS claim_audit_log_prevent_delete
BEFORE DELETE ON claim_audit_log
BEGIN
    SELECT RAISE(ABORT, 'claim_audit_log is append-only: deletes are not allowed');
END;

CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id ON claim_audit_log(claim_id);

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
-- Task-level checkpoints for resumable workflows
CREATE TABLE IF NOT EXISTS task_checkpoints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    workflow_run_id TEXT NOT NULL,
    stage_key TEXT NOT NULL,
    output TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    UNIQUE(claim_id, workflow_run_id, stage_key)
);
CREATE INDEX IF NOT EXISTS idx_task_checkpoints_claim_run
    ON task_checkpoints(claim_id, workflow_run_id);

-- Claim notes for cross-crew communication (agents/crews read and write notes)
CREATE TABLE IF NOT EXISTS claim_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    note TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_notes_claim_id ON claim_notes(claim_id);

-- Follow-up messages: outreach and responses for human-in-the-loop flows
CREATE TABLE IF NOT EXISTS follow_up_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    user_type TEXT NOT NULL,
    message_content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    response_content TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    responded_at TEXT,
    actor_id TEXT DEFAULT 'workflow',
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_follow_up_messages_claim_id ON follow_up_messages(claim_id);
CREATE INDEX IF NOT EXISTS idx_follow_up_messages_status ON follow_up_messages(claim_id, status);

-- Reserve history: append-only audit of reserve changes (actuarial, compliance)
CREATE TABLE IF NOT EXISTS reserve_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    old_amount REAL,
    new_amount REAL NOT NULL,
    reason TEXT DEFAULT '',
    actor_id TEXT DEFAULT 'workflow',
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE TRIGGER IF NOT EXISTS reserve_history_prevent_update
BEFORE UPDATE ON reserve_history
BEGIN
    SELECT RAISE(ABORT, 'reserve_history is append-only: updates are not allowed');
END;
CREATE TRIGGER IF NOT EXISTS reserve_history_prevent_delete
BEFORE DELETE ON reserve_history
BEGIN
    SELECT RAISE(ABORT, 'reserve_history is append-only: deletes are not allowed');
END;
CREATE INDEX IF NOT EXISTS idx_reserve_history_claim_id ON reserve_history(claim_id);

-- Claim tasks: discrete units of future work created by agents or adjusters
CREATE TABLE IF NOT EXISTS claim_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    title TEXT NOT NULL,
    task_type TEXT NOT NULL,
    description TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT NOT NULL DEFAULT 'medium',
    assigned_to TEXT,
    created_by TEXT NOT NULL DEFAULT 'workflow',
    due_date TEXT,
    resolution_notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_id ON claim_tasks(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_tasks_status ON claim_tasks(status);
CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_status ON claim_tasks(claim_id, status);

-- Claim payments: disbursement tracking (authorized -> issued -> cleared/voided)
CREATE TABLE IF NOT EXISTS claim_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    amount REAL NOT NULL,
    payee TEXT NOT NULL,
    payee_type TEXT NOT NULL,
    payment_method TEXT NOT NULL,
    check_number TEXT,
    status TEXT NOT NULL DEFAULT 'authorized',
    authorized_by TEXT NOT NULL,
    issued_at TEXT,
    cleared_at TEXT,
    voided_at TEXT,
    void_reason TEXT,
    payee_secondary TEXT,
    payee_secondary_type TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_payments_claim_id ON claim_payments(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_payments_status ON claim_payments(status);

CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin);
CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date);
"""


def get_db_path() -> str:
    """Return path to SQLite database from settings."""
    from claim_agent.config import get_settings

    return get_settings().paths.claims_db_path


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Run schema migrations for existing databases."""
    try:
        cursor = conn.execute("PRAGMA table_info(claims)")
        columns = {row[1] for row in cursor.fetchall()}
        if "archived_at" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN archived_at TEXT")
        if "loss_state" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN loss_state TEXT")
    except sqlite3.OperationalError:
        pass


def _run_schema(db_path: str) -> None:
    """Create tables if they do not exist. Caller must manage _schema_initialized."""
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)


def init_db(path: str | None = None) -> None:
    """Create tables if they do not exist."""
    db_path = path or get_db_path()
    _run_schema(db_path)
    with _schema_lock:
        _schema_initialized.add(db_path)


def ensure_fresh_db_on_startup() -> None:
    """If FRESH_CLAIMS_DB_ON_STARTUP is true, delete claims DB and reinitialize.

    Call at server startup (e.g. in lifespan) for simulation/dev runs that need
    an empty claims database each time.
    """
    from claim_agent.config import get_settings

    if not get_settings().paths.fresh_claims_db_on_startup:
        return

    db_path = get_db_path()
    p = Path(db_path)
    if p.exists():
        logger.warning(
            "Claims DB wiped on startup (FRESH_CLAIMS_DB_ON_STARTUP=true). "
            "All claims have been deleted."
        )
        p.unlink()
    with _schema_lock:
        _schema_initialized.discard(db_path)
    init_db(db_path)


_fresh_db_ensured: bool = False


def _ensure_schema(db_path: str) -> None:
    """Run schema once per path. Thread-safe."""
    global _fresh_db_ensured
    with _schema_lock:
        if not _fresh_db_ensured:
            _fresh_db_ensured = True
            ensure_fresh_db_on_startup()
    # Fast path: check without lock
    if db_path in _schema_initialized:
        return
    # Slow path: acquire lock and check again (double-checked locking)
    with _schema_lock:
        if db_path in _schema_initialized:
            return
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
