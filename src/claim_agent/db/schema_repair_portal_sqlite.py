"""SQLite DDL for repair shop user accounts and claim assignments.

Used by ``database.py`` (``SCHEMA_SQL``) and Alembic revision 054 so these
definitions stay in one place.

PostgreSQL equivalents use ``TIMESTAMP WITH TIME ZONE`` instead of ``TEXT`` for
temporal columns and ``SERIAL`` for auto-increment primary keys; keep columns,
nullability, and indexes logically aligned when changing schema.
"""

REPAIR_SHOP_USERS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS repair_shop_users (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""

IDX_REPAIR_SHOP_USERS_EMAIL = (
    "CREATE INDEX IF NOT EXISTS idx_repair_shop_users_email ON repair_shop_users(email)"
)
IDX_REPAIR_SHOP_USERS_SHOP_ID = (
    "CREATE INDEX IF NOT EXISTS idx_repair_shop_users_shop_id ON repair_shop_users(shop_id)"
)

REPAIR_SHOP_CLAIM_ASSIGNMENTS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS repair_shop_claim_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    assigned_by TEXT,
    notes TEXT,
    assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id),
    UNIQUE(claim_id, shop_id)
)"""

IDX_RSCA_CLAIM_ID = (
    "CREATE INDEX IF NOT EXISTS idx_repair_shop_assignments_claim_id "
    "ON repair_shop_claim_assignments(claim_id)"
)
IDX_RSCA_SHOP_ID = (
    "CREATE INDEX IF NOT EXISTS idx_repair_shop_assignments_shop_id "
    "ON repair_shop_claim_assignments(shop_id)"
)
