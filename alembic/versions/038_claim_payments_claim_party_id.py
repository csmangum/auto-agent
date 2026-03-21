"""Add claim_party_id to claim_payments for payee linkage to claim_parties.

Revision ID: 038
Revises: 037
Create Date: 2026-03-21
"""

from alembic import op
from sqlalchemy import text

revision = "038"
down_revision = "037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            text(
                "ALTER TABLE claim_payments ADD COLUMN IF NOT EXISTS "
                "claim_party_id INTEGER REFERENCES claim_parties(id)"
            )
        )
    else:
        op.execute(
            text(
                "ALTER TABLE claim_payments ADD COLUMN claim_party_id INTEGER "
                "REFERENCES claim_parties(id)"
            )
        )


def downgrade() -> None:
    op.execute(text("ALTER TABLE claim_payments DROP COLUMN IF EXISTS claim_party_id"))
