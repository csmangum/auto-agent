"""Add indexes on claim_parties for address and provider name lookups.

Revision ID: 018
Revises: 017
Create Date: 2026-03-16

Adds expression indexes to support get_claims_by_party_address and
get_claims_by_provider_name queries used by fraud detection.
"""
from alembic import op
from sqlalchemy import text


revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_claim_parties_address_lower "
        "ON claim_parties(lower(trim(address)))"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_claim_parties_provider_name "
        "ON claim_parties(party_type, lower(trim(name)))"
    ))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute(text("DROP INDEX IF EXISTS idx_claim_parties_provider_name"))
    op.execute(text("DROP INDEX IF EXISTS idx_claim_parties_address_lower"))
