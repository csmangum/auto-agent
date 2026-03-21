"""SQLite DDL for incidents, claim_links, and claims.incident_id (shared bootstrap).

Used by ``database.py`` (``SCHEMA_SQL``, ``_run_migrations``) and Alembic revision 022
so these definitions stay in one place.

PostgreSQL equivalents live in ``alembic/versions/023_postgres_full_schema.py``; keep
columns, nullability, uniqueness, and indexes logically aligned when changing schema.
"""

INCIDENTS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    incident_date TEXT NOT NULL,
    incident_description TEXT,
    loss_state TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
)"""

IDX_INCIDENTS_INCIDENT_DATE = (
    "CREATE INDEX IF NOT EXISTS idx_incidents_incident_date ON incidents(incident_date)"
)

CLAIM_LINKS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS claim_links (
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
)"""

IDX_CLAIM_LINKS_CLAIM_A = (
    "CREATE INDEX IF NOT EXISTS idx_claim_links_claim_a ON claim_links(claim_id_a)"
)
IDX_CLAIM_LINKS_CLAIM_B = (
    "CREATE INDEX IF NOT EXISTS idx_claim_links_claim_b ON claim_links(claim_id_b)"
)

IDX_CLAIMS_INCIDENT_ID = "CREATE INDEX IF NOT EXISTS idx_claims_incident_id ON claims(incident_id)"

# For Alembic 022 after ``incidents`` exists; do not use in _run_migrations before incidents table.
ALTER_CLAIMS_ADD_INCIDENT_ID_FK = (
    "ALTER TABLE claims ADD COLUMN incident_id TEXT REFERENCES incidents(id)"
)
