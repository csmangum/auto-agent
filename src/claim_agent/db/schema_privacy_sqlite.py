"""SQLite DDL for privacy/compliance tables (shared bootstrap).

Covers: dsar_verification_tokens, dpa_registry, cross_border_transfer_log.

Used by ``database.py`` (``SCHEMA_SQL``) and Alembic revisions 046 and 047 so
these definitions stay in one place.

PostgreSQL equivalents use ``SERIAL``/``TIMESTAMP WITH TIME ZONE`` in place of
``INTEGER AUTOINCREMENT``/``TEXT`` for temporal columns; keep columns, nullability,
and indexes logically aligned when changing schema.
"""

DSAR_VERIFICATION_TOKENS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS dsar_verification_tokens (
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
)"""

IDX_DSAR_VERIFICATION_TOKENS_IDENTIFIER = (
    "CREATE INDEX IF NOT EXISTS idx_dsar_verification_tokens_identifier "
    "ON dsar_verification_tokens(claimant_identifier, created_at)"
)

DPA_REGISTRY_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS dpa_registry (
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
)"""

IDX_DPA_REGISTRY_SUBPROCESSOR = (
    "CREATE INDEX IF NOT EXISTS idx_dpa_registry_subprocessor ON dpa_registry(subprocessor_name)"
)
IDX_DPA_REGISTRY_ACTIVE = (
    "CREATE INDEX IF NOT EXISTS idx_dpa_registry_active ON dpa_registry(active)"
)
IDX_DPA_REGISTRY_SERVICE_TYPE = (
    "CREATE INDEX IF NOT EXISTS idx_dpa_registry_service_type ON dpa_registry(service_type)"
)

CROSS_BORDER_TRANSFER_LOG_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS cross_border_transfer_log (
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
)"""

IDX_CBT_LOG_CLAIM_ID = (
    "CREATE INDEX IF NOT EXISTS idx_cbt_log_claim_id ON cross_border_transfer_log(claim_id)"
)
IDX_CBT_LOG_FLOW_NAME = (
    "CREATE INDEX IF NOT EXISTS idx_cbt_log_flow_name ON cross_border_transfer_log(flow_name)"
)
IDX_CBT_LOG_CREATED_AT = (
    "CREATE INDEX IF NOT EXISTS idx_cbt_log_created_at ON cross_border_transfer_log(created_at)"
)
IDX_CBT_LOG_POLICY_DECISION = (
    "CREATE INDEX IF NOT EXISTS idx_cbt_log_policy_decision "
    "ON cross_border_transfer_log(policy_decision)"
)
