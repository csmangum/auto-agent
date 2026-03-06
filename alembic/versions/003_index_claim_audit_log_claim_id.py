"""Add index on claim_audit_log(claim_id) for history queries.

Revision ID: 003
Revises: 002
Create Date: 2026-03-06

"""
from alembic import op
from sqlalchemy import text


revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_claim_audit_log_claim_id ON claim_audit_log(claim_id)"
    ))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_claim_audit_log_claim_id"))
