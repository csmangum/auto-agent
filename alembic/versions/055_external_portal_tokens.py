"""Add external_portal_tokens for unified external portal with role-based access.

Revision ID: 055
Revises: 054

A single ``external_portal_tokens`` table replaces the role-specific legacy
token tables as the preferred way to issue portal credentials.  Each row
carries an explicit ``role`` (claimant | repair_shop | tpa) and a ``scopes``
JSON array so callers know precisely what actions are permitted.

Legacy tables (``claim_access_tokens``, ``repair_shop_access_tokens``,
``third_party_access_tokens``) are NOT altered; new tokens should be issued
via this table while old tokens remain valid until expiry.

Schema management note
~~~~~~~~~~~~~~~~~~~~~~
On SQLite, ``database.py`` SCHEMA_SQL bootstrap also creates this table
(via ``schema_unified_portal_sqlite.py``) using ``CREATE TABLE IF NOT EXISTS``.
This Alembic migration is the **canonical** schema path for PostgreSQL
deployments and is safe to run on bootstrapped SQLite databases (all DDL
uses ``IF NOT EXISTS``).
"""

from alembic import op

from claim_agent.db.schema_unified_portal_sqlite import (
    EXTERNAL_PORTAL_TOKENS_TABLE_SQLITE,
    IDX_EPT_CLAIM_ID,
    IDX_EPT_EXPIRES_AT,
    IDX_EPT_ROLE,
    IDX_EPT_TOKEN_HASH,
)

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None

_PG_EXTERNAL_PORTAL_TOKENS = """
CREATE TABLE IF NOT EXISTS external_portal_tokens (
    id SERIAL PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    role TEXT NOT NULL,
    scopes TEXT NOT NULL DEFAULT '[]',
    claim_id TEXT REFERENCES claims(id),
    shop_id TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute(EXTERNAL_PORTAL_TOKENS_TABLE_SQLITE)
    else:
        op.execute(_PG_EXTERNAL_PORTAL_TOKENS)

    # IDX_EPT_TOKEN_HASH is a UNIQUE index – duplicate of the inline UNIQUE
    # constraint; harmless on SQLite, ensures named index on PostgreSQL.
    op.execute(IDX_EPT_TOKEN_HASH)
    op.execute(IDX_EPT_ROLE)
    op.execute(IDX_EPT_CLAIM_ID)
    op.execute(IDX_EPT_EXPIRES_AT)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS external_portal_tokens")
