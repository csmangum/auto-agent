"""Add settlement workflow flags on claims for state-machine guards.

Revision ID: 033
Revises: 032
Create Date: 2026-03-19

repair_ready_for_settlement / total_loss_settlement_authorized: nullable INTEGER (0/1).
NULL means unset (guards do not apply); 0 blocks open->settled when claim_type matches.
"""

from alembic import op
from sqlalchemy import text

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "repair_ready_for_settlement" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN repair_ready_for_settlement INTEGER"))
        if "total_loss_settlement_authorized" not in columns:
            op.execute(
                text("ALTER TABLE claims ADD COLUMN total_loss_settlement_authorized INTEGER")
            )
    else:
        op.execute(
            text("ALTER TABLE claims ADD COLUMN IF NOT EXISTS repair_ready_for_settlement INTEGER")
        )
        op.execute(
            text(
                "ALTER TABLE claims ADD COLUMN IF NOT EXISTS "
                "total_loss_settlement_authorized INTEGER"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        pass
    else:
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS repair_ready_for_settlement"))
        op.execute(
            text("ALTER TABLE claims DROP COLUMN IF EXISTS total_loss_settlement_authorized")
        )
