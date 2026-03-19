"""Add external_ref to claim_payments for idempotent workflow/API creates.

Revision ID: 032
Revises: 031
Create Date: 2026-03-19
"""
from alembic import op
from sqlalchemy import text


revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            text(
                "ALTER TABLE claim_payments ADD COLUMN IF NOT EXISTS external_ref TEXT"
            )
        )
        op.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_payments_claim_external_ref
                ON claim_payments (claim_id, external_ref)
                WHERE external_ref IS NOT NULL
                """
            )
        )
    else:
        op.execute(text("ALTER TABLE claim_payments ADD COLUMN external_ref TEXT"))
        op.execute(
            text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_payments_claim_external_ref
                ON claim_payments(claim_id, external_ref)
                WHERE external_ref IS NOT NULL
                """
            )
        )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_claim_payments_claim_external_ref"))
    # PostgreSQL and SQLite 3.35+ support DROP COLUMN IF EXISTS (see 029_litigation_hold pattern).
    op.execute(text("ALTER TABLE claim_payments DROP COLUMN IF EXISTS external_ref"))
