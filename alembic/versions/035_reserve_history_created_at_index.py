"""Index reserve_history(created_at) for actuarial period queries.

Revision ID: 035
Revises: 034
Create Date: 2026-03-20
"""

from alembic import op
from sqlalchemy import text

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_reserve_history_created_at "
            "ON reserve_history(created_at)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_reserve_history_created_at"))
