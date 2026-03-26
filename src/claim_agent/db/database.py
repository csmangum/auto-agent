"""Database connection and schema initialization.

Supports SQLite (default) and PostgreSQL. When DATABASE_URL is set, uses
PostgreSQL with connection pooling. Otherwise uses SQLite at claims_db_path.

Async support (PostgreSQL only):
    Use ``get_connection_async()`` in async FastAPI route handlers for
    non-blocking database I/O via the asyncpg driver.  The sync
    ``get_connection()`` remains available for CLI, scripts, and sync callers.
"""

import logging
import os
import sqlite3
import threading
import warnings
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from claim_agent.db.schema_core_sqlite import (
    CLAIM_AUDIT_LOG_TABLE_SQLITE,
    CLAIMS_TABLE_SQLITE,
    IDX_CLAIM_AUDIT_LOG_CLAIM_ID,
    IDX_CLAIM_AUDIT_LOG_CLAIM_ID_ACTION,
    IDX_CLAIMS_INCIDENT_DATE,
    IDX_CLAIMS_VIN,
)
from claim_agent.db.schema_auth_sqlite import (
    IDX_REFRESH_TOKENS_EXPIRES_AT,
    IDX_REFRESH_TOKENS_TOKEN_HASH,
    IDX_REFRESH_TOKENS_USER_ID,
    IDX_USERS_EMAIL,
    REFRESH_TOKENS_TABLE_SQLITE,
    USERS_TABLE_SQLITE,
)
from claim_agent.db.schema_note_templates_sqlite import (
    IDX_NOTE_TEMPLATES_ACTIVE,
    NOTE_TEMPLATES_TABLE_SQLITE,
)
from claim_agent.db.schema_repair_portal_sqlite import (
    IDX_REPAIR_SHOP_USERS_EMAIL,
    IDX_REPAIR_SHOP_USERS_SHOP_ID,
    IDX_RSCA_CLAIM_ID,
    IDX_RSCA_SHOP_ID,
    REPAIR_SHOP_CLAIM_ASSIGNMENTS_TABLE_SQLITE,
    REPAIR_SHOP_USERS_TABLE_SQLITE,
)
from claim_agent.db.schema_incidents_sqlite import (
    CLAIM_LINKS_TABLE_SQLITE,
    INCIDENTS_TABLE_SQLITE,
    IDX_CLAIM_LINKS_CLAIM_A,
    IDX_CLAIM_LINKS_CLAIM_B,
    IDX_CLAIMS_INCIDENT_ID,
    IDX_INCIDENTS_INCIDENT_DATE,
)
from claim_agent.db.schema_privacy_sqlite import (
    CROSS_BORDER_TRANSFER_LOG_TABLE_SQLITE,
    DSAR_VERIFICATION_TOKENS_TABLE_SQLITE,
    DPA_REGISTRY_TABLE_SQLITE,
    IDX_CBT_LOG_CLAIM_ID,
    IDX_CBT_LOG_CREATED_AT,
    IDX_CBT_LOG_FLOW_NAME,
    IDX_CBT_LOG_POLICY_DECISION,
    IDX_DPA_REGISTRY_ACTIVE,
    IDX_DPA_REGISTRY_SERVICE_TYPE,
    IDX_DPA_REGISTRY_SUBPROCESSOR,
    IDX_DSAR_VERIFICATION_TOKENS_IDENTIFIER,
)
from claim_agent.db.schema_unified_portal_sqlite import (
    EXTERNAL_PORTAL_TOKENS_TABLE_SQLITE,
    IDX_EPT_CLAIM_ID,
    IDX_EPT_EXPIRES_AT,
    IDX_EPT_ROLE,
)
from claim_agent.db.schema_rental_sqlite import (
    RENTAL_AUTHORIZATIONS_TABLE_SQLITE,
    IDX_RENTAL_AUTH_CLAIM_ID,
    IDX_RENTAL_AUTH_REIMBURSEMENT_ID,
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
"""
    + CLAIMS_TABLE_SQLITE
    + ";\n"
    + """
-- Claim links: typed relationships between claims (same_incident, opposing_carrier, etc.)
"""
    + CLAIM_LINKS_TABLE_SQLITE
    + ";\n"
    + IDX_CLAIM_LINKS_CLAIM_A
    + ";\n"
    + IDX_CLAIM_LINKS_CLAIM_B
    + ";\n"
    + """

-- Audit log (state changes). UPDATE limited by trigger; DELETE allowed for gated tooling.
"""
    + CLAIM_AUDIT_LOG_TABLE_SQLITE
    + ";\n"
    + """
-- Enforce append-only behavior: allow only PII-field updates (before_state / after_state).
-- Non-PII columns (claim_id, action, statuses, details, actor_id, created_at) are immutable.
-- Note: SQLite's "IS NOT" is the null-safe inequality operator (equivalent to PostgreSQL's
-- "IS DISTINCT FROM"): it treats NULL=NULL as equal, so nullable columns that are NULL in
-- both OLD and NEW will NOT fire the trigger.
CREATE TRIGGER IF NOT EXISTS claim_audit_log_protect_non_pii_columns
BEFORE UPDATE ON claim_audit_log
BEGIN
    SELECT RAISE(ABORT, 'claim_audit_log: only before_state and after_state may be updated')
    WHERE (NEW.claim_id IS NOT OLD.claim_id)
       OR (NEW.action IS NOT OLD.action)
       OR (NEW.old_status IS NOT OLD.old_status)
       OR (NEW.new_status IS NOT OLD.new_status)
       OR (NEW.details IS NOT OLD.details)
       OR (NEW.actor_id IS NOT OLD.actor_id)
       OR (NEW.created_at IS NOT OLD.created_at);
END;

-- DELETE is allowed for gated retention tooling (see migration 039, audit-log-purge CLI).

"""
    + IDX_CLAIM_AUDIT_LOG_CLAIM_ID
    + ";\n"
    + IDX_CLAIM_AUDIT_LOG_CLAIM_ID_ACTION
    + ";\n"
    + """
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
    topic TEXT,
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

"""
    + IDX_CLAIMS_VIN
    + ";\n"
    + IDX_CLAIMS_INCIDENT_DATE
    + ";\n"
    + IDX_CLAIMS_INCIDENT_ID
    + ";\n"
    + """
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

-- Repair shop portal: per-claim magic-link tokens (hashed)
CREATE TABLE IF NOT EXISTS repair_shop_access_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    shop_id TEXT,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
);
CREATE INDEX IF NOT EXISTS idx_repair_shop_tokens_claim_id ON repair_shop_access_tokens(claim_id);
CREATE INDEX IF NOT EXISTS idx_repair_shop_tokens_token_hash ON repair_shop_access_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_repair_shop_tokens_expires_at ON repair_shop_access_tokens(expires_at);

-- Third-party portal: per-claim magic-link tokens (hashed) for counterparties
CREATE TABLE IF NOT EXISTS third_party_access_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    token_hash TEXT NOT NULL,
    party_id INTEGER,
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    FOREIGN KEY (party_id) REFERENCES claim_parties(id)
);
CREATE INDEX IF NOT EXISTS idx_third_party_tokens_claim_id ON third_party_access_tokens(claim_id);
CREATE INDEX IF NOT EXISTS idx_third_party_tokens_token_hash ON third_party_access_tokens(token_hash);
CREATE INDEX IF NOT EXISTS idx_third_party_tokens_expires_at ON third_party_access_tokens(expires_at);

-- DPA registry: track Data Processing Agreements with subprocessors (GDPR Art. 28)
"""
    + DPA_REGISTRY_TABLE_SQLITE
    + ";\n"
    + IDX_DPA_REGISTRY_SUBPROCESSOR
    + ";\n"
    + IDX_DPA_REGISTRY_ACTIVE
    + ";\n"
    + IDX_DPA_REGISTRY_SERVICE_TYPE
    + ";\n"
    + """
-- Cross-border transfer log: audit trail of data flows across jurisdictions
"""
    + CROSS_BORDER_TRANSFER_LOG_TABLE_SQLITE
    + ";\n"
    + IDX_CBT_LOG_CLAIM_ID
    + ";\n"
    + IDX_CBT_LOG_FLOW_NAME
    + ";\n"
    + IDX_CBT_LOG_CREATED_AT
    + ";\n"
    + IDX_CBT_LOG_POLICY_DECISION
    + ";\n"
    + """
-- DSAR OTP verification tokens for self-service claimant identity proofing
"""
    + DSAR_VERIFICATION_TOKENS_TABLE_SQLITE
    + ";\n"
    + IDX_DSAR_VERIFICATION_TOKENS_IDENTIFIER
    + ";\n"
    + """
-- Users (Auth Phase 2): password login and RBAC identity (id aligns with claims.assignee)
"""
    + USERS_TABLE_SQLITE
    + ";\n"
    + IDX_USERS_EMAIL
    + ";\n"
    + """
-- Refresh tokens: store hashes only; opaque bearer rotated on /api/auth/refresh
"""
    + REFRESH_TOKENS_TABLE_SQLITE
    + ";\n"
    + IDX_REFRESH_TOKENS_USER_ID
    + ";\n"
    + IDX_REFRESH_TOKENS_TOKEN_HASH
    + ";\n"
    + IDX_REFRESH_TOKENS_EXPIRES_AT
    + ";\n"
    + """
-- Note templates: server-driven adjuster quick-insert snippets
"""
    + NOTE_TEMPLATES_TABLE_SQLITE
    + ";\n"
    + IDX_NOTE_TEMPLATES_ACTIVE
    + ";\n"
    + """
-- Repair shop user accounts: shop-level login for multi-claim portal access
"""
    + REPAIR_SHOP_USERS_TABLE_SQLITE
    + ";\n"
    + IDX_REPAIR_SHOP_USERS_EMAIL
    + ";\n"
    + IDX_REPAIR_SHOP_USERS_SHOP_ID
    + ";\n"
    + """
-- Repair shop claim assignments: explicit shop ↔ claim pairings with audit trail
"""
    + REPAIR_SHOP_CLAIM_ASSIGNMENTS_TABLE_SQLITE
    + ";\n"
    + IDX_RSCA_CLAIM_ID
    + ";\n"
    + IDX_RSCA_SHOP_ID
    + ";\n"
    + """
-- Unified external portal tokens: role-bearing, hashed tokens for any external role
"""
    + EXTERNAL_PORTAL_TOKENS_TABLE_SQLITE
    + ";\n"
    + IDX_EPT_ROLE
    + ";\n"
    + IDX_EPT_CLAIM_ID
    + ";\n"
    + IDX_EPT_EXPIRES_AT
    + ";\n"
)

SCHEMA_SQL += (
    """
-- Rental authorizations: structured rental arrangements persisted when rental crew completes
"""
    + RENTAL_AUTHORIZATIONS_TABLE_SQLITE
    + ";\n"
    + IDX_RENTAL_AUTH_CLAIM_ID
    + ";\n"
    + IDX_RENTAL_AUTH_REIMBURSEMENT_ID
    + ";\n"
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
            # Relative paths: sqlite:///relative.db; absolute POSIX: sqlite:////abs/path.db
            from pathlib import Path

            path_str = Path(db_path).as_posix()
            url = f"sqlite:///{path_str}"
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


def _find_alembic_dir() -> Path:
    """Locate the Alembic scripts directory.

    Checks (in order):
    1. ``ALEMBIC_SCRIPT_LOCATION`` from settings (explicit path for wheel / non-repo layouts).
    2. The project root inferred from this module's file path (editable / development installs).
    3. The current working directory (CLI / script usage from the project root).

    Raises:
        RuntimeError: If no valid Alembic scripts directory exists.
    """
    from claim_agent.config import get_settings

    override = (get_settings().paths.alembic_script_location or "").strip()
    if override:
        candidate = Path(override).expanduser().resolve()
        if candidate.is_dir():
            return candidate
        raise RuntimeError(
            f"ALEMBIC_SCRIPT_LOCATION is set but is not a directory: {candidate}"
        )

    # Editable install path: src/claim_agent/db/database.py → parents[3] == project root.
    candidate = Path(__file__).resolve().parents[3] / "alembic"
    if candidate.is_dir():
        return candidate
    # Fallback: running from project root (e.g. pytest, CLI)
    candidate = Path.cwd() / "alembic"
    if candidate.is_dir():
        return candidate
    raise RuntimeError(
        "Alembic scripts directory not found. Set ALEMBIC_SCRIPT_LOCATION to the path of "
        "the `alembic` folder (repository root), or install editable from the repo "
        "(`pip install -e .`) and run from the project root."
    )


def _run_alembic_migrations(db_path: str, is_legacy: bool = False) -> None:
    """Apply pending Alembic migrations to a SQLite database.

    Uses Alembic as the single source of truth for schema evolution, replacing
    the previous inline ``_run_migrations()`` approach.

    * **New databases** (``alembic_version`` table absent, ``is_legacy=False``): the
      full schema has already been created by :func:`_run_schema` via ``SCHEMA_SQL``.
      The head revision is *stamped* so that future ``alembic upgrade head`` calls
      are no-ops without re-running every migration.
    * **Existing databases** (``alembic_version`` table present): ``upgrade head``
      is run to apply any pending migrations in revision order.
    * **Legacy databases** (tables exist but no ``alembic_version``, ``is_legacy=True``):
      ``upgrade head`` is run to apply missing column additions and other schema
      changes. Note that some early migrations create tables without ``IF NOT EXISTS``
      guards; legacy detection ensures these are only run when needed.

    Args:
        db_path: Path to the SQLite database file.
        is_legacy: If True, indicates this is a legacy database (tables existed
            before _run_schema was called). If False, indicates a fresh database.

    Raises:
        RuntimeError: If the Alembic scripts directory cannot be resolved (see
            :func:`_find_alembic_dir`).
        Exception: Propagates Alembic command failures so startup does not continue with a
            partially migrated or unstamped database.
    """
    alembic_dir = _find_alembic_dir()

    db_abs = os.path.abspath(db_path)

    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(alembic_dir))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_abs}")
    # Suppress Alembic's own INFO-level console logging during programmatic use.
    cfg.attributes["configure_logger"] = False

    # Determine whether to stamp (fresh DB) or upgrade (existing/legacy DB).
    with sqlite3.connect(db_path) as check_conn:
        try:
            check_conn.execute("SELECT 1 FROM alembic_version LIMIT 1")
            has_version_table = True
        except sqlite3.OperationalError:
            has_version_table = False

    try:
        if has_version_table:
            # Database already has Alembic version tracking: run pending migrations.
            command.upgrade(cfg, "head")
        elif is_legacy:
            # Legacy database: tables exist but no alembic_version. Run upgrade to
            # apply missing column additions and other schema changes.
            command.upgrade(cfg, "head")
        else:
            # Fresh database: schema already created via SCHEMA_SQL; stamp only.
            # Migrations are NOT fully idempotent (some use CREATE TABLE without
            # IF NOT EXISTS), so we must avoid running them on fresh databases.
            command.stamp(cfg, "head")
    except Exception:
        logger.exception(
            "Failed to apply Alembic migrations for SQLite database '%s'.",
            db_path,
        )
        raise


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Deprecated: inline SQLite schema migrations.

    .. deprecated::
        Inline schema migrations have been replaced by Alembic to ensure a single
        source of truth for both SQLite and PostgreSQL backends and prevent schema
        drift.  This function is now a no-op.

        * For **new** SQLite databases created via :func:`init_db` / :func:`_run_schema`,
          Alembic stamps the head revision automatically.
        * For **existing** databases, run ``alembic upgrade head`` from the project root
          (this also applies to automated upgrades via :func:`_run_alembic_migrations`).
        * For **PostgreSQL**, Alembic has always been the sole migration mechanism.

        This function will be removed in a future release.
    """
    warnings.warn(
        "_run_migrations() is deprecated and is now a no-op. "
        "Schema migrations are managed exclusively by Alembic. "
        "Run 'alembic upgrade head' from the project root to migrate an existing database. "
        "See: https://alembic.sqlalchemy.org/en/latest/",
        DeprecationWarning,
        stacklevel=2,
    )


def _run_schema(db_path: str) -> None:
    """Create tables if they do not exist (SQLite only). Caller must manage _schema_initialized."""
    if is_postgres_backend():
        return  # PostgreSQL uses Alembic only
    p = Path(db_path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Check if claims table exists BEFORE running SCHEMA_SQL to distinguish
    # fresh databases from legacy (pre-Alembic) databases.
    had_claims_table = False
    if p.exists():
        with sqlite3.connect(db_path) as conn:
            try:
                conn.execute("SELECT 1 FROM claims LIMIT 1")
                had_claims_table = True
            except sqlite3.OperationalError:
                had_claims_table = False

    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
    _run_alembic_migrations(db_path, is_legacy=had_claims_table)


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
    except Exception:
        conn.rollback()
        raise
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
