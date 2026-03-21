"""Unique edge (from_party_id, to_party_id, relationship_type).

Revision ID: 037
Revises: 036
Create Date: 2026-03-20
"""

from alembic import op
from sqlalchemy import text

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_claim_party_relationships_edge "
            "ON claim_party_relationships(from_party_id, to_party_id, relationship_type)"
        )
    )


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS uq_claim_party_relationships_edge"))
