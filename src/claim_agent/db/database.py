"""Database connection and schema initialization.

Supports SQLite (default) and PostgreSQL. When DATABASE_URL is set, uses
PostgreSQL with connection pooling. Otherwise uses SQLite at claims_db_path.
"""

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)

# Tracks which database paths have had schema applied (avoid running on every connection)
_schema_initialized: set[str] = set()
_schema_lock = threading.RLock()

# SQLAlchemy engine (lazy init). For PostgreSQL: single engine. For SQLite: default engine.
_engine: Engine | None = None
_engine_lock = threading.Lock()
# SQLite engines for override paths (e.g. tests)
_sqlite_engines: dict[str, Engine] = {}

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
    litigation_hold INTEGER DEFAULT 0,
    repair_ready_for_settlement INTEGER,
    total_loss_settlement_authorized INTEGER,
    retention_tier TEXT NOT NULL DEFAULT 'active',
    purged_at TEXT,
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
CREATE INDEX IF NOT EXISTS idx_reserve_history_created_at ON reserve_history(created_at);

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
    external_ref TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_payments_claim_id ON claim_payments(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_payments_status ON claim_payments(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_payments_claim_external_ref ON claim_payments(claim_id, external_ref) WHERE external_ref IS NOT NULL;

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
    consent_status TEXT DEFAULT 'pending',
    authorization_status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_parties_claim_id ON claim_parties(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_parties_claim_type ON claim_parties(claim_id, party_type);

-- Party-to-party edges (e.g. represented_by, lienholder_for)
CREATE TABLE IF NOT EXISTS claim_party_relationships (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_party_id INTEGER NOT NULL,
    to_party_id INTEGER NOT NULL,
    relationship_type TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (from_party_id) REFERENCES claim_parties(id) ON DELETE CASCADE,
    FOREIGN KEY (to_party_id) REFERENCES claim_parties(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_from ON claim_party_relationships(from_party_id);
CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_to ON claim_party_relationships(to_party_id);
CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_from_type
    ON claim_party_relationships(from_party_id, relationship_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_party_relationships_edge
    ON claim_party_relationships(from_party_id, to_party_id, relationship_type);

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

-- DSAR: Data Subject Access Request tables for privacy compliance
CREATE TABLE IF NOT EXISTS dsar_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    claimant_identifier TEXT NOT NULL,
    request_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    requested_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    actor_id TEXT,
    notes TEXT,
    verification_data TEXT
);
CREATE INDEX IF NOT EXISTS idx_dsar_requests_request_id ON dsar_requests(request_id);
CREATE INDEX IF NOT EXISTS idx_dsar_requests_status ON dsar_requests(status);
CREATE INDEX IF NOT EXISTS idx_dsar_requests_claimant ON dsar_requests(claimant_identifier);

CREATE TABLE IF NOT EXISTS dsar_exports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL,
    export_path TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (request_id) REFERENCES dsar_requests(request_id)
);
CREATE INDEX IF NOT EXISTS idx_dsar_exports_request_id ON dsar_exports(request_id);

CREATE TABLE IF NOT EXISTS dsar_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT,
    action TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_dsar_audit_log_request_id ON dsar_audit_log(request_id);
CREATE INDEX IF NOT EXISTS idx_dsar_audit_log_action ON dsar_audit_log(action);

-- Claim access tokens: claimant portal magic-link style access
CREATE TABLE IF NOT EXISTS claim_access_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    party_id INTEGER,
    email TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    FOREIGN KEY (party_id) REFERENCES claim_parties(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_access_tokens_claim_id ON claim_access_tokens(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_access_tokens_token_hash ON claim_access_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_claim_access_tokens_expires_at ON claim_access_tokens(expires_at);
"""


def _get_database_url() -> str:
    """Return database URL: DATABASE_URL if set, else sqlite:///path."""
    from claim_agent.config import get_settings

    settings = get_settings()
    if settings.paths.database_url:
        return settings.paths.database_url
    path = settings.paths.claims_db_path
    return f"sqlite:///{path}"


def _is_postgres() -> bool:
    """True if using PostgreSQL (DATABASE_URL set)."""
    from claim_agent.config import get_settings

    return bool(get_settings().paths.database_url)


def _get_engine() -> Engine:
    """Return SQLAlchemy engine. Lazy init with connection pooling for PostgreSQL."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        url = _get_database_url()
        if _is_postgres():
            _engine = create_engine(url, pool_size=5, max_overflow=10)
        else:
            _engine = create_engine(url, poolclass=NullPool)
    return _engine


def _get_engine_for_path(path: str | None) -> Engine:
    """Return engine for the given path. For PostgreSQL, path is ignored."""
    if _is_postgres():
        return _get_engine()
    from claim_agent.config import get_settings

    settings = get_settings()
    db_path = path or settings.paths.claims_db_path
    if db_path == settings.paths.claims_db_path:
        return _get_engine()
    with _engine_lock:
        if db_path not in _sqlite_engines:
            url = f"sqlite:///{db_path}" if db_path.startswith("/") else f"sqlite:///{db_path}"
            _sqlite_engines[db_path] = create_engine(url, poolclass=NullPool)
        return _sqlite_engines[db_path]


def reset_engine_cache() -> None:
    """Clear cached engines. Use when config (e.g. DATABASE_URL) changes (e.g. tests)."""
    global _engine
    with _engine_lock:
        _engine = None
        _sqlite_engines.clear()


def get_db_path() -> str:
    """Return path to SQLite database from settings. For PostgreSQL, returns path from URL or empty."""
    from claim_agent.config import get_settings

    if _is_postgres():
        return ""  # No file path for PostgreSQL
    return get_settings().paths.claims_db_path


def row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a database row to dict. Works with sqlite3.Row and SQLAlchemy Row."""
    if hasattr(row, "_mapping"):
        return dict(row._mapping)
    return dict(row)


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
        if "litigation_hold" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN litigation_hold INTEGER DEFAULT 0")
        if "repair_ready_for_settlement" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN repair_ready_for_settlement INTEGER")
        if "total_loss_settlement_authorized" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN total_loss_settlement_authorized INTEGER")
        if "retention_tier" not in columns:
            conn.execute(
                "ALTER TABLE claims ADD COLUMN retention_tier TEXT NOT NULL DEFAULT 'active'"
            )
        if "purged_at" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN purged_at TEXT")
        conn.execute("UPDATE claims SET retention_tier = 'archived' WHERE status = 'archived'")
        conn.execute("UPDATE claims SET retention_tier = 'cold' WHERE status = 'closed'")
        # UCSPA compliance (migration 026)
        for col, col_type in [
            ("acknowledged_at", "TEXT"),
            ("acknowledgment_due", "TEXT"),
            ("investigation_due", "TEXT"),
            ("payment_due", "TEXT"),
            ("denial_reason", "TEXT"),
            ("denial_letter_sent_at", "TEXT"),
            ("denial_letter_body", "TEXT"),
        ]:
            if col not in columns:
                conn.execute(f"ALTER TABLE claims ADD COLUMN {col} {col_type}")
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
        conn.execute("SELECT 1 FROM claim_documents LIMIT 1")
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
    # Idempotency keys for duplicate request prevention (claim-before-process pattern)
    try:
        conn.execute("SELECT 1 FROM idempotency_keys LIMIT 1")
        # Add status column if missing (for DBs created before 025)
        cursor = conn.execute("PRAGMA table_info(idempotency_keys)")
        ik_columns = {row[1] for row in cursor.fetchall()}
        if "status" not in ik_columns:
            conn.execute(
                "ALTER TABLE idempotency_keys ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'"
            )
    except sqlite3.OperationalError:
        conn.executescript("""
            CREATE TABLE idempotency_keys (
                idempotency_key TEXT PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'completed',
                response_status INTEGER NOT NULL,
                response_body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at);
        """)
    # Fraud report filings for compliance audit (migration 027)
    try:
        conn.execute("SELECT 1 FROM fraud_report_filings LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript("""
            CREATE TABLE fraud_report_filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                siu_case_id TEXT,
                filing_type TEXT NOT NULL,
                state TEXT,
                report_id TEXT NOT NULL,
                filed_at TEXT NOT NULL,
                filed_by TEXT NOT NULL DEFAULT 'siu_crew',
                indicators_count INTEGER DEFAULT 0,
                template_version TEXT,
                metadata TEXT,
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            );
            CREATE INDEX IF NOT EXISTS idx_fraud_filings_claim_id ON fraud_report_filings(claim_id);
            CREATE INDEX IF NOT EXISTS idx_fraud_filings_filing_type ON fraud_report_filings(filing_type);
        """)
    # claim_payments.external_ref + idempotency index (existing SQLite DBs pre-column)
    try:
        cursor = conn.execute("PRAGMA table_info(claim_payments)")
        cp_columns = {row[1] for row in cursor.fetchall()}
        if cp_columns and "external_ref" not in cp_columns:
            conn.execute("ALTER TABLE claim_payments ADD COLUMN external_ref TEXT")
        if cp_columns:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_payments_claim_external_ref "
                "ON claim_payments(claim_id, external_ref) WHERE external_ref IS NOT NULL"
            )
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reserve_history_created_at ON reserve_history(created_at)"
        )
    except sqlite3.OperationalError:
        pass


def _run_schema(db_path: str) -> None:
    """Create tables if they do not exist (SQLite only). Caller must manage _schema_initialized."""
    if _is_postgres():
        return  # PostgreSQL uses Alembic only
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)


def init_db(path: str | None = None) -> None:
    """Create tables if they do not exist. SQLite only; PostgreSQL uses Alembic."""
    from claim_agent.config import get_settings

    if _is_postgres():
        return
    db_path = path or get_settings().paths.claims_db_path
    _run_schema(db_path)
    with _schema_lock:
        _schema_initialized.add(db_path)


def ensure_fresh_db_on_startup() -> None:
    """If FRESH_CLAIMS_DB_ON_STARTUP is true, delete claims DB and reinitialize.

    SQLite only. For PostgreSQL, run alembic downgrade base && upgrade head.
    Call at server startup (e.g. in lifespan) for simulation/dev runs.
    """
    from claim_agent.config import get_settings

    if _is_postgres():
        return
    if not get_settings().paths.fresh_claims_db_on_startup:
        return

    db_path = get_settings().paths.claims_db_path
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
    """Context manager yielding a SQLAlchemy Connection. Ensures schema exists for SQLite."""
    from claim_agent.config import get_settings

    db_path = path or get_settings().paths.claims_db_path
    if not _is_postgres():
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        _ensure_schema(db_path)
    engine = _get_engine_for_path(path)
    conn = engine.connect()
    if not _is_postgres():
        conn.execute(text("PRAGMA foreign_keys = ON"))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
