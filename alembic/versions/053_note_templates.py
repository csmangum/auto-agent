"""Add note_templates table for server-driven adjuster quick-insert templates.

Revision ID: 053
Revises: 052
"""

from alembic import op

from claim_agent.db.schema_note_templates_sqlite import (
    IDX_NOTE_TEMPLATES_ACTIVE,
    NOTE_TEMPLATES_TABLE_SQLITE,
)

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None

NOTE_TEMPLATES_TABLE_POSTGRES = """CREATE TABLE IF NOT EXISTS note_templates (
    id SERIAL PRIMARY KEY,
    label TEXT NOT NULL,
    body TEXT NOT NULL,
    category TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)"""


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute(NOTE_TEMPLATES_TABLE_SQLITE)
    else:
        op.execute(NOTE_TEMPLATES_TABLE_POSTGRES)
    op.execute(IDX_NOTE_TEMPLATES_ACTIVE)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS note_templates")
