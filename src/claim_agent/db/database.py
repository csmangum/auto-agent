"""Database connection and schema initialization.

Supports SQLite (default) and PostgreSQL. When DATABASE_URL is set, uses
PostgreSQL with connection pooling. Otherwise uses SQLite at claims_db_path.

Async support (PostgreSQL only):
    Use ``get_connection_async()`` in async FastAPI route handlers for
    non-blocking database I/O via the asyncpg driver.  The sync
    ``get_connection()`` remains available for CLI, scripts, and sync callers.
"""

import logging
import sqlite3
import threading
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from claim_agent.db.schema_incidents_sqlite import (
    CLAIM_LINKS_TABLE_SQLITE,
    INCIDENTS_TABLE_SQLITE,
    IDX_CLAIM_LINKS_CLAIM_A,
    IDX_CLAIM_LINKS_CLAIM_B,
    IDX_CLAIMS_INCIDENT_ID,
    IDX_INCIDENTS_INCIDENT_DATE,
)

logger = logging.getLogger(__name__)

# Tracks which database paths have had schema applied (avoid running on every connection)
_schema_initialized: set[str] = set()
_schema_lock = threading.RLock()

# SQLAlchemy engine (lazy init). For PostgreSQL: single engine. For SQLite: default engine.
_engine: Engine | None = None
_engine_lock = threading.Lock()
# SQLite engines for override paths (e.g. tests)
_sqlite_engines: dict[str, Engine] = {}
# Read-replica engine (PostgreSQL only; None when READ_REPLICA_DATABASE_URL is not set)
_replica_engine: Engine | None = None
_replica_engine_lock = threading.Lock()

# Async engine (PostgreSQL only, lazy init). Used by get_connection_async().
_async_engine: AsyncEngine | None = None
_async_engine_lock = threading.Lock()

SCHEMA_SQL = (
    """
-- Incidents table: groups multiple claims under one event (multi-vehicle accident)
"""
    + INCIDENTS_TABLE_SQLITE
    + ";\n"
    + IDX_INCIDENTS_INCIDENT_DATE
    + ";\n"
    + """

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
    cold_storage_exported_at TEXT,
    cold_storage_export_key TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Claim links: typed relationships between claims (same_incident, opposing_carrier, etc.)
"""
    + CLAIM_LINKS_TABLE_SQLITE
    + ";\n"
    + IDX_CLAIM_LINKS_CLAIM_A
    + ";\n"
    + IDX_CLAIM_LINKS_CLAIM_B
    + ";\n"
    + """

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

-- DELETE is allowed for gated retention tooling (see migration 039, audit-log-purge CLI).

CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id ON claim_audit_log(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id_action ON claim_audit_log(claim_id, action);

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
    retention_enforced_at TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    extracted_data TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_id ON claim_documents(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_type ON claim_documents(claim_id, document_type);
CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_review ON claim_documents(claim_id, review_status);
CREATE INDEX IF NOT EXISTS idx_claim_documents_retention_eligible
    ON claim_documents(retention_date)
    WHERE retention_enforced_at IS NULL AND retention_date IS NOT NULL
        AND length(trim(retention_date)) > 0;

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
    claim_party_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    FOREIGN KEY (claim_party_id) REFERENCES claim_parties(id)
);
CREATE INDEX IF NOT EXISTS idx_claim_payments_claim_id ON claim_payments(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_payments_status ON claim_payments(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_payments_claim_external_ref ON claim_payments(claim_id, external_ref) WHERE external_ref IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin);
CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date);
"""
    + IDX_CLAIMS_INCIDENT_ID
    + """;

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

-- DPA registry: track Data Processing Agreements with subprocessors (GDPR Art. 28)
CREATE TABLE IF NOT EXISTS dpa_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subprocessor_name TEXT NOT NULL,
    service_type TEXT NOT NULL,
    data_categories TEXT NOT NULL DEFAULT '[]',
    purpose TEXT NOT NULL,
    destination_country TEXT NOT NULL,
    destination_zone TEXT NOT NULL,
    mechanism TEXT NOT NULL,
    legal_basis TEXT,
    dpa_signed_date TEXT,
    dpa_expiry_date TEXT,
    dpa_document_ref TEXT,
    supplementary_measures TEXT DEFAULT '[]',
    active INTEGER NOT NULL DEFAULT 1,
    notes TEXT,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_dpa_registry_subprocessor ON dpa_registry(subprocessor_name);
CREATE INDEX IF NOT EXISTS idx_dpa_registry_active ON dpa_registry(active);
CREATE INDEX IF NOT EXISTS idx_dpa_registry_service_type ON dpa_registry(service_type);

-- Cross-border transfer log: audit trail of data flows across jurisdictions
CREATE TABLE IF NOT EXISTS cross_border_transfer_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT,
    flow_name TEXT NOT NULL,
    source_zone TEXT NOT NULL,
    destination TEXT NOT NULL,
    destination_zone TEXT NOT NULL,
    data_categories TEXT NOT NULL DEFAULT '[]',
    mechanism TEXT NOT NULL,
    permitted INTEGER NOT NULL DEFAULT 1,
    policy_decision TEXT NOT NULL DEFAULT 'allow',
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cbt_log_claim_id ON cross_border_transfer_log(claim_id);
CREATE INDEX IF NOT EXISTS idx_cbt_log_flow_name ON cross_border_transfer_log(flow_name);
CREATE INDEX IF NOT EXISTS idx_cbt_log_created_at ON cross_border_transfer_log(created_at);
CREATE INDEX IF NOT EXISTS idx_cbt_log_policy_decision ON cross_border_transfer_log(policy_decision);
-- DSAR OTP verification tokens for self-service claimant identity proofing
CREATE TABLE IF NOT EXISTS dsar_verification_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    verification_id TEXT NOT NULL UNIQUE,
    claimant_identifier TEXT NOT NULL,
    channel TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    verified_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_dsar_verification_tokens_identifier
    ON dsar_verification_tokens(claimant_identifier, created_at);

-- Users (Auth Phase 2): password login and RBAC identity (id aligns with claims.assignee)
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- Refresh tokens: store hashes only; opaque bearer rotated on /api/auth/refresh
CREATE TABLE IF NOT EXISTS refresh_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    replaced_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at);
"""
)


def _get_database_url() -> str:
    """Return database URL: DATABASE_URL if set, else sqlite:///path."""
    from claim_agent.config import get_settings

    settings = get_settings()
    if settings.paths.database_url:
        return settings.paths.database_url
    path = settings.paths.claims_db_path
    return f"sqlite:///{path}"


def is_postgres_backend() -> bool:
    """True if using PostgreSQL (``DATABASE_URL`` is set).

    Public API for callers that need to branch on database backend.
    """
    from claim_agent.config import get_settings

    return bool(get_settings().paths.database_url)


def has_read_replica() -> bool:
    """True if a PostgreSQL read-replica is configured (``READ_REPLICA_DATABASE_URL`` is set).

    Returns False when not using PostgreSQL or when no replica URL is provided.
    """
    from claim_agent.config import get_settings

    paths = get_settings().paths
    return bool(is_postgres_backend() and paths.read_replica_database_url)


def _get_replica_engine() -> Engine:
    """Return SQLAlchemy engine for the read replica. Lazy init with connection pooling.

    Falls back to the primary engine when ``READ_REPLICA_DATABASE_URL`` is not set.
    """
    global _replica_engine
    if _replica_engine is not None:
        return _replica_engine
    with _replica_engine_lock:
        if _replica_engine is not None:
            return _replica_engine
        from claim_agent.config import get_settings

        paths = get_settings().paths
        if not paths.read_replica_database_url:
            # No replica configured — fall back to primary
            return _get_engine()
        _replica_engine = create_engine(
            paths.read_replica_database_url,
            pool_size=paths.db_pool_size,
            max_overflow=paths.db_max_overflow,
        )
    return _replica_engine


def _get_engine() -> Engine:
    """Return SQLAlchemy engine. Lazy init with connection pooling for PostgreSQL."""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        url = _get_database_url()
        if is_postgres_backend():
            from claim_agent.config import get_settings

            paths = get_settings().paths
            _engine = create_engine(
                url,
                pool_size=paths.db_pool_size,
                max_overflow=paths.db_max_overflow,
            )
        else:
            _engine = create_engine(url, poolclass=NullPool)
    return _engine


def _get_engine_for_path(path: str | None) -> Engine:
    """Return engine for the given path. For PostgreSQL, path is ignored."""
    if is_postgres_backend():
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
    global _engine, _async_engine, _replica_engine
    with _engine_lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        for eng in _sqlite_engines.values():
            eng.dispose()
        _sqlite_engines.clear()
    with _replica_engine_lock:
        if _replica_engine is not None:
            _replica_engine.dispose()
        _replica_engine = None
    with _async_engine_lock:
        if _async_engine is not None:
            # Dispose underlying sync engine to close pooled connections immediately.
            # AsyncEngine.sync_engine.dispose() is safe to call from sync context.
            _async_engine.sync_engine.dispose()
        _async_engine = None


def _get_async_database_url() -> str:
    """Return async-compatible database URL for SQLAlchemy.

    Converts ``postgresql://`` / ``postgres://`` to ``postgresql+asyncpg://``
    so SQLAlchemy uses the asyncpg driver.  Only valid when
    ``is_postgres_backend()`` is True; raises ``RuntimeError`` otherwise.
    """
    if not is_postgres_backend():
        raise RuntimeError(
            "Async database connections require PostgreSQL (DATABASE_URL must be set). "
            "SQLite does not support the asyncpg driver."
        )
    from claim_agent.config import get_settings

    database_url: str | None = get_settings().paths.database_url
    if not database_url:
        raise RuntimeError(
            "Async database connections require PostgreSQL (DATABASE_URL must be set)."
        )
    # Replace the scheme so SQLAlchemy uses asyncpg.
    if database_url.startswith("postgresql+asyncpg://"):
        return database_url
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+asyncpg://", 1)
    if database_url.startswith("postgresql+"):
        raise RuntimeError(
            "Async database connections require the asyncpg driver. "
            f"Got DATABASE_URL={database_url!r}. Use 'postgresql://', 'postgres://', "
            "or 'postgresql+asyncpg://'."
        )
    raise RuntimeError(
        "Async database connections require a PostgreSQL DATABASE_URL starting with "
        "'postgresql://', 'postgres://', or 'postgresql+asyncpg://'. "
        f"Got DATABASE_URL={database_url!r}."
    )


def _get_async_engine() -> AsyncEngine:
    """Return async SQLAlchemy engine (PostgreSQL only). Lazy init with connection pooling."""
    global _async_engine
    if _async_engine is not None:
        return _async_engine
    with _async_engine_lock:
        if _async_engine is not None:
            return _async_engine
        from claim_agent.config import get_settings

        paths = get_settings().paths
        _async_engine = create_async_engine(
            _get_async_database_url(),
            pool_size=paths.db_pool_size,
            max_overflow=paths.db_max_overflow,
        )
    return _async_engine


@asynccontextmanager
async def get_connection_async():
    """Async context manager yielding a SQLAlchemy ``AsyncConnection`` (PostgreSQL only).

    Use this in async FastAPI route handlers to avoid blocking the event loop.
    The sync ``get_connection()`` remains available for CLI, scripts, and other
    sync callers and continues to work for both SQLite and PostgreSQL.

    Example::

        async with get_connection_async() as conn:
            result = await conn.execute(text("SELECT 1"))

    Raises:
        RuntimeError: If called when the backend is SQLite (DATABASE_URL not set).
    """
    engine = _get_async_engine()
    async with engine.connect() as conn:
        try:
            yield conn
            await conn.commit()
        except Exception:
            await conn.rollback()
            raise


def get_db_path() -> str:
    """Return path to SQLite database from settings. For PostgreSQL, returns path from URL or empty."""
    from claim_agent.config import get_settings

    if is_postgres_backend():
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
            ("denial_letter_delivery_method", "TEXT"),
            ("denial_letter_tracking_id", "TEXT"),
            ("denial_letter_delivered_at", "TEXT"),
            ("settlement_agreed_at", "TEXT"),
            ("last_claimant_communication_at", "TEXT"),
            ("communication_response_due", "TEXT"),
        ]:
            if col not in columns:
                conn.execute(f"ALTER TABLE claims ADD COLUMN {col} {col_type}")
        if "incident_latitude" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN incident_latitude REAL")
        if "incident_longitude" not in columns:
            conn.execute("ALTER TABLE claims ADD COLUMN incident_longitude REAL")
        conn.execute(IDX_CLAIMS_INCIDENT_ID)
    except sqlite3.OperationalError:
        pass
    # Incidents and claim_links for multi-vehicle support
    try:
        conn.execute("SELECT 1 FROM incidents LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript(
            INCIDENTS_TABLE_SQLITE + ";\n" + IDX_INCIDENTS_INCIDENT_DATE + ";\n"
        )
    try:
        conn.execute("SELECT 1 FROM claim_links LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript(
            CLAIM_LINKS_TABLE_SQLITE
            + ";\n"
            + IDX_CLAIM_LINKS_CLAIM_A
            + ";\n"
            + IDX_CLAIM_LINKS_CLAIM_B
            + ";\n"
        )
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
                retention_enforced_at TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                extracted_data TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            );
            CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_id ON claim_documents(claim_id);
            CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_type ON claim_documents(claim_id, document_type);
            CREATE INDEX IF NOT EXISTS idx_claim_documents_claim_review ON claim_documents(claim_id, review_status);
            CREATE INDEX IF NOT EXISTS idx_claim_documents_retention_eligible
                ON claim_documents(retention_date)
                WHERE retention_enforced_at IS NULL AND retention_date IS NOT NULL
                    AND length(trim(retention_date)) > 0;
        """)
    try:
        cursor = conn.execute("PRAGMA table_info(claim_documents)")
        cd_columns = {row[1] for row in cursor.fetchall()}
        if cd_columns and "retention_enforced_at" not in cd_columns:
            conn.execute("ALTER TABLE claim_documents ADD COLUMN retention_enforced_at TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_claim_documents_retention_eligible "
            "ON claim_documents(retention_date) "
            "WHERE retention_enforced_at IS NULL AND retention_date IS NOT NULL "
            "AND length(trim(retention_date)) > 0"
        )
    except sqlite3.OperationalError:
        pass
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
    # claim_payments.external_ref, claim_party_id + idempotency index (existing SQLite DBs)
    try:
        cursor = conn.execute("PRAGMA table_info(claim_payments)")
        cp_columns = {row[1] for row in cursor.fetchall()}
        if cp_columns and "external_ref" not in cp_columns:
            conn.execute("ALTER TABLE claim_payments ADD COLUMN external_ref TEXT")
        if cp_columns and "claim_party_id" not in cp_columns:
            conn.execute(
                "ALTER TABLE claim_payments ADD COLUMN claim_party_id INTEGER "
                "REFERENCES claim_parties(id)"
            )
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
    # claim_party_relationships: directed typed edges replacing claim_parties.represented_by_id
    try:
        conn.execute("SELECT 1 FROM claim_party_relationships LIMIT 1")
    except sqlite3.OperationalError:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS claim_party_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                from_party_id INTEGER NOT NULL,
                to_party_id INTEGER NOT NULL,
                relationship_type TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (from_party_id) REFERENCES claim_parties(id) ON DELETE CASCADE,
                FOREIGN KEY (to_party_id) REFERENCES claim_parties(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_from
                ON claim_party_relationships(from_party_id);
            CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_to
                ON claim_party_relationships(to_party_id);
            CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_from_type
                ON claim_party_relationships(from_party_id, relationship_type);
            CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_party_relationships_edge
                ON claim_party_relationships(from_party_id, to_party_id, relationship_type);
        """)
        # Backfill existing represented_by_id values into the new edges table.
        try:
            cursor = conn.execute("PRAGMA table_info(claim_parties)")
            cp_columns = {row[1] for row in cursor.fetchall()}
            if "represented_by_id" in cp_columns:
                # 'represented_by' matches PartyRelationshipType.REPRESENTED_BY.value
                conn.execute("""
                    INSERT OR IGNORE INTO claim_party_relationships
                        (from_party_id, to_party_id, relationship_type)
                    SELECT id, represented_by_id, 'represented_by'
                    FROM claim_parties
                    WHERE represented_by_id IS NOT NULL
                """)
        except sqlite3.OperationalError:
            pass
    # GitHub #350: drop legacy delete trigger so audit-log-purge works (schema no longer creates it).
    try:
        conn.execute("DROP TRIGGER IF EXISTS claim_audit_log_prevent_delete")
    except sqlite3.OperationalError:
        pass


def _run_schema(db_path: str) -> None:
    """Create tables if they do not exist (SQLite only). Caller must manage _schema_initialized."""
    if is_postgres_backend():
        return  # PostgreSQL uses Alembic only
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        _run_migrations(conn)


def init_db(path: str | None = None) -> None:
    """Create tables if they do not exist. SQLite only; PostgreSQL uses Alembic."""
    from claim_agent.config import get_settings

    if is_postgres_backend():
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

    if is_postgres_backend():
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
    if not is_postgres_backend():
        p = Path(db_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        _ensure_schema(db_path)
    engine = _get_engine_for_path(path)
    conn = engine.connect()
    if not is_postgres_backend():
        conn.execute(text("PRAGMA foreign_keys = ON"))
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_replica_connection():
    """Context manager yielding a read-only SQLAlchemy Connection to the read replica.

    When ``READ_REPLICA_DATABASE_URL`` is set and ``DATABASE_URL`` is also set, the
    connection is made to the replica. Otherwise falls back to the primary connection
    via :func:`get_connection`.

    Use this for read-heavy, non-mutating queries (reporting, analytics, audit log
    queries, etc.) to offload traffic from the primary database.

    Example::

        with get_replica_connection() as conn:
            rows = conn.execute(text("SELECT * FROM claims WHERE status = :s"), {"s": "open"}).fetchall()

    Note: Do **not** use this connection for write operations — replicas are read-only.
    """
    if not has_read_replica():
        with get_connection() as conn:
            yield conn
        return

    engine = _get_replica_engine()
    conn = engine.connect()
    try:
        yield conn
    finally:
        conn.close()


@event.listens_for(Engine, "connect")
def _sqlite_register_graph_phone_digits(dbapi_conn, _connection_record):
    """Register SQLite UDF so relationship snapshot phone matching matches Python normalization."""
    if not isinstance(dbapi_conn, sqlite3.Connection):
        return
    from claim_agent.utils.graph_contact_normalize import normalize_party_phone_for_graph

    def _impl(s: str | bytes | None) -> str:
        if s is None:
            return ""
        text_s = s.decode("utf-8") if isinstance(s, bytes) else str(s)
        return normalize_party_phone_for_graph(text_s) or ""

    dbapi_conn.create_function("graph_phone_digits", 1, _impl)
