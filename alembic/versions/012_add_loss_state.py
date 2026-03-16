"""Add loss_state column to claims for multi-state compliance.

Revision ID: 012
Revises: 011
Create Date: 2026-03-16

Adds loss_state/jurisdiction field to support state-specific:
- Prompt payment deadlines (CA: 30 days, FL: 90 days, etc.)
- Total loss thresholds
- Compliance RAG context routing
"""
from alembic import op
from sqlalchemy import text


revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "loss_state" not in columns:
        op.execute(text("ALTER TABLE claims ADD COLUMN loss_state TEXT"))


def downgrade() -> None:
    # SQLite does not support DROP COLUMN; leave column in place for safety.
    pass
