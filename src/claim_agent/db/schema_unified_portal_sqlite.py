"""SQLite DDL for the unified external portal token table.

``external_portal_tokens`` is a single table that issues signed, hashed tokens
for *any* external-portal role (claimant, repair_shop, tpa, …).  Each token
carries:
- ``role``     – the portal role granted (e.g. ``claimant``, ``repair_shop``)
- ``scopes``   – JSON array of fine-grained permissions (e.g. ``["read_claim", "upload_doc"]``)
- ``claim_id`` – required for session resolution (API rejects unified tokens without it)
- ``shop_id``  – set for repair_shop tokens issued via shop-level registration
- ``revoked_at`` – NULL while the token is valid; set to revoke without deletion

Legacy tables (``claim_access_tokens``, ``repair_shop_access_tokens``) remain
unchanged for backward compatibility; new tokens should use this table.

PostgreSQL equivalents use ``TIMESTAMPTZ`` instead of ``TEXT`` for temporal
columns and ``SERIAL`` for the PK; keep columns, nullability, and indexes
logically aligned when changing schema.
"""

EXTERNAL_PORTAL_TOKENS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS external_portal_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT '[]',
    claim_id TEXT,
    shop_id TEXT,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (claim_id) REFERENCES claims(id)
)"""

IDX_EPT_ROLE = (
    "CREATE INDEX IF NOT EXISTS idx_external_portal_tokens_role "
    "ON external_portal_tokens(role)"
)
IDX_EPT_CLAIM_ID = (
    "CREATE INDEX IF NOT EXISTS idx_external_portal_tokens_claim_id "
    "ON external_portal_tokens(claim_id)"
)
IDX_EPT_EXPIRES_AT = (
    "CREATE INDEX IF NOT EXISTS idx_external_portal_tokens_expires_at "
    "ON external_portal_tokens(expires_at)"
)
