"""SQLite DDL for the core claims and claim_audit_log tables (shared bootstrap).

Used by ``database.py`` (``SCHEMA_SQL``) and serves as the canonical column-set
reference for parity tests against ``alembic/versions/023_postgres_full_schema.py``
plus the later ADD-COLUMN migrations (029, 033, 034, 050).

PostgreSQL equivalents live in the Alembic migrations; keep column names and
nullability logically aligned when changing either side.
"""

CLAIMS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS claims (
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
    total_loss_metadata TEXT,
    liability_percentage REAL,
    liability_basis TEXT,
    litigation_hold INTEGER DEFAULT 0,
    repair_ready_for_settlement INTEGER,
    total_loss_settlement_authorized INTEGER,
    retention_tier TEXT NOT NULL DEFAULT 'active',
    purged_at TEXT,
    cold_storage_exported_at TEXT,
    cold_storage_export_key TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)"""

IDX_CLAIMS_VIN = "CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin)"
IDX_CLAIMS_INCIDENT_DATE = (
    "CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date)"
)

CLAIM_AUDIT_LOG_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS claim_audit_log (
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
)"""

IDX_CLAIM_AUDIT_LOG_CLAIM_ID = (
    "CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id ON claim_audit_log(claim_id)"
)
IDX_CLAIM_AUDIT_LOG_CLAIM_ID_ACTION = (
    "CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id_action"
    " ON claim_audit_log(claim_id, action)"
)
