"""Add repair_shop_access_tokens for repair shop self-service portal.

Revision ID: 051
Revises: 050

Per-claim magic tokens (hashed) for external repair shops, parallel to
claim_access_tokens for claimants.
"""

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS repair_shop_access_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                shop_id TEXT,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS repair_shop_access_tokens (
                id SERIAL PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(id),
                token_hash TEXT NOT NULL,
                shop_id TEXT,
                expires_at TIMESTAMPTZ NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repair_shop_tokens_claim_id "
        "ON repair_shop_access_tokens(claim_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repair_shop_tokens_token_hash "
        "ON repair_shop_access_tokens(token_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repair_shop_tokens_expires_at "
        "ON repair_shop_access_tokens(expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS repair_shop_access_tokens")
