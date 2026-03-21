"""Composite index on claim_audit_log(claim_id, action) for document audit queries.

Revision ID: 040
Revises: 039
Create Date: 2026-03-21

GitHub issue #283: chain-of-custody / document access audit rows filtered by action.
"""

from alembic import op
from sqlalchemy import text

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id_action "
            "ON claim_audit_log(claim_id, action)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_claim_audit_log_claim_id_action"))
