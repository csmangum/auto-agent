"""Add UCSPA (Unfair Claims Settlement Practices Act) compliance fields.

Revision ID: 026
Revises: 025
Create Date: 2026-03-18

Adds state-specific SLA tracking per NAIC Model UCSPA:
- acknowledged_at: when claim receipt was acknowledged
- acknowledgment_due, investigation_due, payment_due: state-specific deadlines
- denial_reason, denial_letter_sent_at, denial_letter_body: denial tracking
"""
from alembic import op
from sqlalchemy import text


revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        new_cols = [
            ("acknowledged_at", "TEXT"),
            ("acknowledgment_due", "TEXT"),
            ("investigation_due", "TEXT"),
            ("payment_due", "TEXT"),
            ("denial_reason", "TEXT"),
            ("denial_letter_sent_at", "TEXT"),
            ("denial_letter_body", "TEXT"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in columns:
                op.execute(text(f"ALTER TABLE claims ADD COLUMN {col_name} {col_type}"))
    else:
        # PostgreSQL: add columns one at a time (IF NOT EXISTS per column)
        for col, col_type in [
            ("acknowledged_at", "TEXT"),
            ("acknowledgment_due", "TEXT"),
            ("investigation_due", "TEXT"),
            ("payment_due", "TEXT"),
            ("denial_reason", "TEXT"),
            ("denial_letter_sent_at", "TEXT"),
            ("denial_letter_body", "TEXT"),
        ]:
            op.execute(f"ALTER TABLE claims ADD COLUMN IF NOT EXISTS {col} {col_type}")


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        # SQLite does not support DROP COLUMN; leave columns in place for data preservation.
        pass
    else:
        # PostgreSQL: drop the added columns in reverse order.
        _UCSPA_COLUMNS = [
            "denial_letter_body",
            "denial_letter_sent_at",
            "denial_reason",
            "payment_due",
            "investigation_due",
            "acknowledgment_due",
            "acknowledged_at",
        ]
        for col in _UCSPA_COLUMNS:
            op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS " + col))
