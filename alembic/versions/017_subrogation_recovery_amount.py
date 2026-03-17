"""Add recovery_amount to subrogation_cases for record_recovery persistence.

Revision ID: 017
Revises: 016
Create Date: 2026-03-16

Adds recovery_amount (REAL) for tracking actual recovery when record_recovery
updates subrogation case status (pending, partial, full, closed_no_recovery).
"""
from alembic import op
from sqlalchemy import text


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(subrogation_cases)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "recovery_amount" not in columns:
        op.execute(text("ALTER TABLE subrogation_cases ADD COLUMN recovery_amount REAL"))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    # SQLite does not support DROP COLUMN; leave column in place for safety.
    pass
