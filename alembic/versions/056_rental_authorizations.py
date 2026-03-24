"""Add rental_authorizations table for structured rental arrangement persistence.

Revision ID: 056
Revises: 055

Persists structured rental authorization records when the rental crew
completes processing (Phase 3 of the claimant portal rental feature).

Each row captures:
- reservation_ref / agency_ref  (internal; not exposed to claimant portal)
- authorized_days, daily_cap    (limits from the policy)
- direct_bill                   (carrier direct-bill vs. claimant reimbursement)
- status                        (authorized | in_progress | completed | cancelled)
- reimbursement_id              (RENT-* idempotency key from rental_logic)
- amount_approved               (total approved amount)
"""

from alembic import op

from claim_agent.db.schema_rental_sqlite import (
    IDX_RENTAL_AUTH_CLAIM_ID,
    IDX_RENTAL_AUTH_REIMBURSEMENT_ID,
    RENTAL_AUTHORIZATIONS_TABLE_SQLITE,
)

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None

_PG_RENTAL_AUTHORIZATIONS = """
CREATE TABLE IF NOT EXISTS rental_authorizations (
    id SERIAL PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(id),
    reservation_ref TEXT,
    agency_ref TEXT,
    authorized_days INTEGER NOT NULL,
    daily_cap REAL NOT NULL,
    direct_bill INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'authorized',
    reimbursement_id TEXT,
    amount_approved REAL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (status IN ('authorized', 'in_progress', 'completed', 'cancelled'))
)
"""

_PG_IDX_RENTAL_AUTH_CLAIM_ID = (
    "CREATE INDEX IF NOT EXISTS idx_rental_authorizations_claim_id "
    "ON rental_authorizations(claim_id)"
)

_PG_IDX_RENTAL_AUTH_REIMBURSEMENT_ID = (
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_rental_authorizations_reimbursement_id "
    "ON rental_authorizations(reimbursement_id) WHERE reimbursement_id IS NOT NULL"
)


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute(RENTAL_AUTHORIZATIONS_TABLE_SQLITE)
        op.execute(IDX_RENTAL_AUTH_CLAIM_ID)
        op.execute(IDX_RENTAL_AUTH_REIMBURSEMENT_ID)
    else:
        op.execute(_PG_RENTAL_AUTHORIZATIONS)
        op.execute(_PG_IDX_RENTAL_AUTH_CLAIM_ID)
        op.execute(_PG_IDX_RENTAL_AUTH_REIMBURSEMENT_ID)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rental_authorizations")
