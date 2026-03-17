"""Add total_loss_metadata column to claims.

Revision ID: 016
Revises: 015
Create Date: 2026-03-16

Adds total_loss_metadata (TEXT/JSON) for:
- ACV breakdown, salvage deduction, owner_retain
- dmv_reference, salvage_title_status
"""
from alembic import op
from sqlalchemy import text


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "total_loss_metadata" not in columns:
        op.execute(text("ALTER TABLE claims ADD COLUMN total_loss_metadata TEXT"))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    # SQLite does not support DROP COLUMN; leave column in place for safety.
    pass
