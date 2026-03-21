"""Add settlement_agreed_at for UCSPA prompt-payment from settlement.

Revision ID: 042
Revises: 041
Create Date: 2026-03-21

When a claim first transitions to ``settled``, ``settlement_agreed_at`` is set and
``payment_due`` is recomputed from that moment using state prompt-payment days
(FNOL-based payment_due remains until settlement).
"""
from alembic import op
from sqlalchemy import text


revision = "042"
down_revision = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "settlement_agreed_at" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN settlement_agreed_at TEXT"))
    else:
        op.execute(
            text("ALTER TABLE claims ADD COLUMN IF NOT EXISTS settlement_agreed_at TEXT")
        )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "sqlite":
        pass
    else:
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS settlement_agreed_at"))
