"""Add third_party_access_tokens for third-party self-service portal.

Revision ID: 052
Revises: 051

Per-claim magic tokens (hashed) for external third parties (counterparties,
lienholders, etc.), parallel to repair_shop_access_tokens.
"""

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS third_party_access_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                party_id INTEGER,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id),
                FOREIGN KEY (party_id) REFERENCES claim_parties(id)
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS third_party_access_tokens (
                id SERIAL PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(id),
                token_hash TEXT NOT NULL,
                party_id INTEGER REFERENCES claim_parties(id),
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_third_party_tokens_claim_id "
        "ON third_party_access_tokens(claim_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_third_party_tokens_token_hash "
        "ON third_party_access_tokens(token_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_third_party_tokens_expires_at "
        "ON third_party_access_tokens(expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS third_party_access_tokens")
