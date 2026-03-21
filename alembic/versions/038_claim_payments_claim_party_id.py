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
        # For SQLite (and other non-PostgreSQL dialects), first check whether
        # the column already exists to avoid duplicate-column errors when the
        # application has already applied schema changes outside Alembic.
        existing_columns_result = bind.execute(text("PRAGMA table_info(claim_payments)"))
        existing_column_names = {row[1] for row in existing_columns_result}
        if "claim_party_id" not in existing_column_names:
            op.execute(
                text(
                    "ALTER TABLE claim_payments ADD COLUMN claim_party_id INTEGER "
                    "REFERENCES claim_parties(id)"
                )
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(text("ALTER TABLE claim_payments DROP COLUMN IF EXISTS claim_party_id"))
    else:
        # SQLite does not support DROP COLUMN IF EXISTS; leave column in place for safety.
        pass
