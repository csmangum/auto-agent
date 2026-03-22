"""Add denial letter delivery metadata columns to claims.

Revision ID: 045
Revises: 044
Create Date: 2026-03-22

Tracks denial letter delivery proof metadata for UCSPA workflows:
- denial_letter_delivery_method: mail|email|certified_mail
- denial_letter_tracking_id: carrier tracking id (typically certified mail)
- denial_letter_delivered_at: delivery confirmation timestamp
"""
from alembic import op
from sqlalchemy import text


revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "denial_letter_delivery_method" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN denial_letter_delivery_method TEXT"))
        if "denial_letter_tracking_id" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN denial_letter_tracking_id TEXT"))
        if "denial_letter_delivered_at" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN denial_letter_delivered_at TEXT"))
    else:
        op.execute(
            text(
                "ALTER TABLE claims ADD COLUMN IF NOT EXISTS denial_letter_delivery_method TEXT"
            )
        )
        op.execute(
            text("ALTER TABLE claims ADD COLUMN IF NOT EXISTS denial_letter_tracking_id TEXT")
        )
        op.execute(
            text("ALTER TABLE claims ADD COLUMN IF NOT EXISTS denial_letter_delivered_at TEXT")
        )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        return
    else:
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS denial_letter_delivered_at"))
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS denial_letter_tracking_id"))
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS denial_letter_delivery_method"))
