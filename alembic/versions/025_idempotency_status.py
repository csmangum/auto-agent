"""Add status column to idempotency_keys for claim-before-process pattern.

Revision ID: 025
Revises: 024
Create Date: 2026-03-17

Prevents race condition: first request inserts with status=in_progress,
processes, then updates to completed. Duplicate requests see in_progress
and return 409, or see completed and return cached response.
"""
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
            ALTER TABLE idempotency_keys ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'
        """)
    else:
        op.execute("""
            ALTER TABLE idempotency_keys ADD COLUMN status TEXT NOT NULL DEFAULT 'completed'
        """)


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "sqlite":
        # SQLite doesn't support DROP COLUMN easily; recreate table
        op.execute("""
            CREATE TABLE idempotency_keys_backup (
                idempotency_key TEXT PRIMARY KEY,
                response_status INTEGER NOT NULL,
                response_body TEXT NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )
        """)
        op.execute("""
            INSERT INTO idempotency_keys_backup
            SELECT idempotency_key, response_status, response_body, created_at, expires_at
            FROM idempotency_keys
        """)
        op.execute("DROP TABLE idempotency_keys")
        op.execute("ALTER TABLE idempotency_keys_backup RENAME TO idempotency_keys")
        op.execute("CREATE INDEX IF NOT EXISTS idx_idempotency_expires ON idempotency_keys(expires_at)")
    else:
        op.execute("ALTER TABLE idempotency_keys DROP COLUMN status")
