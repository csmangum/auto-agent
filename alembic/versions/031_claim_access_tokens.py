"""Add claim_access_tokens table for claimant portal access.

Revision ID: 031
Revises: 030
Create Date: 2026-03-18

Claim access tokens for claimant self-service portal. Tokens grant
claimant access to specific claims (magic-link style).
"""
from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
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
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS claim_access_tokens (
                id SERIAL PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(id),
                token_hash TEXT NOT NULL,
                party_id INTEGER REFERENCES claim_parties(id),
                email TEXT,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_access_tokens_claim_id ON claim_access_tokens(claim_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_access_tokens_token_hash ON claim_access_tokens(token_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_access_tokens_expires_at ON claim_access_tokens(expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS claim_access_tokens")
