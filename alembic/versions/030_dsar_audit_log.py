"""Add dsar_audit_log table for DSAR operation audit trail.

Revision ID: 030
Revises: 029
Create Date: 2026-03-18

Audit trail for access fulfill, deletion fulfill, consent revoke.
"""
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS dsar_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT,
                action TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS dsar_audit_log (
                id SERIAL PRIMARY KEY,
                request_id TEXT,
                action TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_audit_log_request_id ON dsar_audit_log(request_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_audit_log_action ON dsar_audit_log(action)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dsar_audit_log")
