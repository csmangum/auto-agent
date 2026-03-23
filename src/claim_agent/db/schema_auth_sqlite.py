"""SQLite DDL for users and refresh_tokens (Auth Phase 2 – shared bootstrap).

Used by ``database.py`` (``SCHEMA_SQL``) and Alembic revision 048 so these
definitions stay in one place.

PostgreSQL equivalents use ``TIMESTAMP WITH TIME ZONE`` instead of ``TEXT`` for
temporal columns and ``SERIAL`` for auto-increment primary keys; keep columns,
nullability, and indexes logically aligned when changing schema.
"""

USERS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""

IDX_USERS_EMAIL = "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"

REFRESH_TOKENS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS refresh_tokens (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    replaced_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""

IDX_REFRESH_TOKENS_USER_ID = (
    "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id ON refresh_tokens(user_id)"
)
IDX_REFRESH_TOKENS_TOKEN_HASH = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash ON refresh_tokens(token_hash)"
)
IDX_REFRESH_TOKENS_EXPIRES_AT = (
    "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at ON refresh_tokens(expires_at)"
)
