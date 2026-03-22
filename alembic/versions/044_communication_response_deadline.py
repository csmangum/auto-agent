"""Add last_claimant_communication_at and communication_response_due to claims.

Revision ID: 044
Revises: 043
Create Date: 2026-03-22

UCSPA requires insurers to respond to claimant communications within state-specific
timeframes. This migration adds two columns to track that obligation:

- ``last_claimant_communication_at``: UTC timestamp of the most recent inbound
  claimant communication (updated by ClaimRepository.record_claimant_communication).
- ``communication_response_due``: ISO date by which the insurer must respond
  (recomputed from last_claimant_communication_at + state communication_response_days).

PostgreSQL: ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` requires PostgreSQL 9.1+.

SQLite downgrade: ``downgrade()`` is a no-op on SQLite. Dropping columns was not
supported before SQLite 3.35.0 (March 2021); a rebuild migration would be needed to
remove these columns on older embedded SQLite builds.
"""
from alembic import op
from sqlalchemy import text


revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "last_claimant_communication_at" not in columns:
            op.execute(
                text("ALTER TABLE claims ADD COLUMN last_claimant_communication_at TEXT")
            )
        if "communication_response_due" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN communication_response_due TEXT"))
    else:
        # IF NOT EXISTS: PostgreSQL 9.1+
        op.execute(
            text(
                "ALTER TABLE claims ADD COLUMN IF NOT EXISTS"
                " last_claimant_communication_at TEXT"
            )
        )
        op.execute(
            text(
                "ALTER TABLE claims ADD COLUMN IF NOT EXISTS communication_response_due TEXT"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        # See module docstring: no DROP COLUMN on SQLite here (version / rebuild constraints).
        return
    else:
        op.execute(
            text("ALTER TABLE claims DROP COLUMN IF EXISTS communication_response_due")
        )
        op.execute(
            text("ALTER TABLE claims DROP COLUMN IF EXISTS last_claimant_communication_at")
        )
