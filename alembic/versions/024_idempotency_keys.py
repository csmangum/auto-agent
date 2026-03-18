"""Add idempotency_keys table for duplicate request prevention.

Revision ID: 024
Revises: 023
Create Date: 2026-03-17

Stores idempotency keys with response cache and TTL to prevent duplicate
claim creation on network retries.
"""
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                idempotency_key TEXT PRIMARY KEY,
                response_status INTEGER NOT NULL,
                response_body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at)")
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS idempotency_keys (
                idempotency_key TEXT PRIMARY KEY,
                response_status INTEGER NOT NULL,
                response_body TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_idempotency_expires")
    op.execute("DROP TABLE IF EXISTS idempotency_keys")
