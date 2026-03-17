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
-- Incidents table: groups multiple claims under one event (multi-vehicle accident)
CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    incident_date TEXT NOT NULL,
    incident_description TEXT,
    loss_state TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_incidents_incident_date ON incidents(incident_date);

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
    incident_id TEXT REFERENCES incidents(id),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Claim links: typed relationships between claims (same_incident, opposing_carrier, etc.)
CREATE TABLE IF NOT EXISTS claim_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id_a TEXT NOT NULL,
    claim_id_b TEXT NOT NULL,
    link_type TEXT NOT NULL,
    opposing_carrier TEXT,
    notes TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id_a) REFERENCES claims(id),
    FOREIGN KEY (claim_id_b) REFERENCES claims(id),
    UNIQUE (claim_id_a, claim_id_b, link_type)
);
CREATE INDEX IF NOT EXISTS idx_claim_links_claim_a ON claim_links(claim_id_a);
CREATE INDEX IF NOT EXISTS idx_claim_links_claim_b ON claim_links(claim_id_b);

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

-- Document requests: request -> receipt tracking (created before claim_tasks for FK)
CREATE TABLE IF NOT EXISTS document_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    document_type TEXT NOT NULL,
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    requested_from TEXT,
    status TEXT NOT NULL DEFAULT 'requested',
    received_at TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_document_requests_claim_id ON document_requests(claim_id);

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
    document_request_id INTEGER,
    recurrence_rule TEXT,
    recurrence_interval INTEGER,
    parent_task_id INTEGER REFERENCES claim_tasks(id),
    escalation_level INTEGER NOT NULL DEFAULT 0,
    escalation_notified_at TEXT,
    escalation_escalated_at TEXT,
    auto_created_from TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    FOREIGN KEY (document_request_id) REFERENCES document_requests(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_id ON claim_tasks(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_tasks_status ON claim_tasks(status);
CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_status ON claim_tasks(claim_id, status);
CREATE INDEX IF NOT EXISTS idx_claim_tasks_due_date ON claim_tasks(due_date) WHERE due_date IS NOT NULL AND status NOT IN ('completed', 'cancelled');
CREATE INDEX IF NOT EXISTS idx_claim_tasks_parent_task ON claim_tasks(parent_task_id) WHERE parent_task_id IS NOT NULL;

-- Claim documents: structured document metadata (type, received_from, review_status, etc.)
CREATE TABLE IF NOT EXISTS claim_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    document_type TEXT,
    received_date TEXT,
    received_from TEXT,
    review_status TEXT NOT NULL DEFAULT 'pending',
    privileged INTEGER NOT NULL DEFAULT 0,
    retention_date TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    extracted_data TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_id ON claim_documents(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_type ON claim_documents(claim_id, document_type);
CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_review ON claim_documents(claim_id, review_status);

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
CREATE INDEX IF NOT EXISTS idx_claims_incident_id ON claims(incident_id);

-- Claim parties: claimant, policyholder, witness, attorney, provider, lienholder
CREATE TABLE IF NOT EXISTS claim_parties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    party_type TEXT NOT NULL,
    name TEXT,
    email TEXT,
    phone TEXT,
    address TEXT,
    role TEXT,
    represented_by_id INTEGER,
    consent_status TEXT DEFAULT 'pending',
    authorization_status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    FOREIGN KEY (represented_by_id) REFERENCES claim_parties(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_parties_claim_id ON claim_parties(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_parties_claim_type ON claim_parties(claim_id, party_type);

-- Subrogation cases: recovery tracking and inter-company arbitration
CREATE TABLE IF NOT EXISTS subrogation_cases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    case_id TEXT NOT NULL UNIQUE,
    amount_sought REAL NOT NULL,
    opposing_carrier TEXT,
    status TEXT DEFAULT 'pending',
    arbitration_status TEXT,
    arbitration_forum TEXT,
    dispute_date TEXT,
    liability_percentage REAL,
    liability_basis TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_subrogation_cases_claim_id ON subrogation_cases(claim_id);

-- Repair status: partial loss repair progress (received -> disassembly -> ... -> ready)
CREATE TABLE IF NOT EXISTS repair_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    authorization_id TEXT,
    status TEXT NOT NULL,
    status_updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    notes TEXT,
    paused_at TEXT,
    pause_reason TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_repair_status_claim_id ON repair_status(claim_id);
CREATE INDEX IF NOT EXISTS idx_repair_status_shop_status ON repair_status(shop_id, status);
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
        if "liability_percentage" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN liability_percentage REAL")
        if "liability_basis" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN liability_basis TEXT")
        if "total_loss_metadata" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN total_loss_metadata TEXT")
        if "incident_id" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN incident_id TEXT")
    except sqlite3.OperationalError:
        pass
    # Incidents and claim_links for multi-vehicle support
    try:
        conn.execute("SELECT 1 FROM incidents LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript("""
            CREATE TABLE incidents (
                id TEXT PRIMARY KEY,
                incident_date TEXT NOT NULL,
                incident_description TEXT,
                loss_state TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_incidents_incident_date ON incidents(incident_date);
        """)
    try:
        conn.execute("SELECT 1 FROM claim_links LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript("""
            CREATE TABLE claim_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id_a TEXT NOT NULL,
                claim_id_b TEXT NOT NULL,
                link_type TEXT NOT NULL,
                opposing_carrier TEXT,
                notes TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id_a) REFERENCES claims(id),
                FOREIGN KEY (claim_id_b) REFERENCES claims(id),
                UNIQUE (claim_id_a, claim_id_b, link_type)
            );
            CREATE INDEX IF NOT EXISTS idx_claim_links_claim_a ON claim_links(claim_id_a);
            CREATE INDEX IF NOT EXISTS idx_claim_links_claim_b ON claim_links(claim_id_b);
        """)
    try:
        cursor = conn.execute("PRAGMA table_info(subrogation_cases)")
        sc_columns = {row[1] for row in cursor.fetchall()}
        if "recovery_amount" not in sc_columns:
            conn.execute("ALTER TABLE subrogation_cases ADD COLUMN recovery_amount REAL")
    except sqlite3.OperationalError:
        pass
    # Document management: claim_documents, document_requests, claim_tasks.document_request_id
    try:
        conn.execute(
            "SELECT 1 FROM claim_documents LIMIT 1"
        )
    except sqlite3.OperationalError:
        conn.executescript("""
            CREATE TABLE claim_documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                storage_key TEXT NOT NULL,
                document_type TEXT,
                received_date TEXT,
                received_from TEXT,
                review_status TEXT NOT NULL DEFAULT 'pending',
                privileged INTEGER NOT NULL DEFAULT 0,
                retention_date TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                extracted_data TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            );
            CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_id ON claim_documents(claim_id);
            CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_type ON claim_documents(claim_id, document_type);
            CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_review ON claim_documents(claim_id, review_status);
        """)
    try:
        conn.execute("SELECT 1 FROM document_requests LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript("""
            CREATE TABLE document_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                document_type TEXT NOT NULL,
                requested_at TEXT NOT NULL DEFAULT (datetime('now')),
                requested_from TEXT,
                status TEXT NOT NULL DEFAULT 'requested',
                received_at TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            );
            CREATE INDEX IF NOT EXISTS idx_document_requests_claim_id ON document_requests(claim_id);
        """)
    try:
        cursor = conn.execute("PRAGMA table_info(claim_tasks)")
        ct_columns = {row[1] for row in cursor.fetchall()}
        if "document_request_id" not in ct_columns:
            conn.execute(
                "ALTER TABLE claim_tasks ADD COLUMN document_request_id INTEGER "
                "REFERENCES document_requests(id)"
            )
        for col, typ in [
            ("recurrence_rule", "TEXT"),
            ("recurrence_interval", "INTEGER"),
            ("parent_task_id", "INTEGER REFERENCES claim_tasks(id)"),
            ("escalation_level", "INTEGER NOT NULL DEFAULT 0"),
            ("escalation_notified_at", "TEXT"),
            ("escalation_escalated_at", "TEXT"),
            ("auto_created_from", "TEXT"),
        ]:
            if col not in ct_columns:
                conn.execute(f"ALTER TABLE claim_tasks ADD COLUMN {col} {typ}")
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
