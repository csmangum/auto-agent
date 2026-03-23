"""Add note_templates table for server-driven adjuster quick-insert templates.

Revision ID: 053
Revises: 052
"""

from alembic import op

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS note_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                label TEXT NOT NULL,
                body TEXT NOT NULL,
                category TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_by TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS note_templates (
                id SERIAL PRIMARY KEY,
                label TEXT NOT NULL,
                body TEXT NOT NULL,
                category TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_note_templates_active ON note_templates(is_active)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS note_templates")
