"""Add liability_percentage and liability_basis to claims.

Revision ID: 014
Revises: 013
Create Date: 2026-03-16

Adds structured liability determination fields for:
- liability_percentage: insured's share of fault (0-100)
- liability_basis: reasoning/source for the determination
"""
from alembic import op
from sqlalchemy import text


revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "liability_percentage" not in columns:
        op.execute(text("ALTER TABLE claims ADD COLUMN liability_percentage REAL"))
    if "liability_basis" not in columns:
        op.execute(text("ALTER TABLE claims ADD COLUMN liability_basis TEXT"))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    # SQLite does not support DROP COLUMN; leave columns in place for safety.
    pass
