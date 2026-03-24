"""Add repair_shop_users and repair_shop_claim_assignments for multi-claim portal accounts.

Revision ID: 054
Revises: 053

Repair shop user accounts (shop_id, email, password) allow a shop to authenticate
once and view all assigned claims rather than juggling one per-claim magic token
per repair order.  The repair_shop_claim_assignments table records explicit
claim <-> shop pairings with an audit trail (assigned_by, assigned_at).

Backward-compatible: existing repair_shop_access_tokens (per-claim tokens) are
not altered.
"""

from alembic import op

from claim_agent.db.schema_repair_portal_sqlite import (
    IDX_REPAIR_SHOP_USERS_EMAIL,
    IDX_REPAIR_SHOP_USERS_SHOP_ID,
    IDX_RSCA_CLAIM_ID,
    IDX_RSCA_SHOP_ID,
    REPAIR_SHOP_CLAIM_ASSIGNMENTS_TABLE_SQLITE,
    REPAIR_SHOP_USERS_TABLE_SQLITE,
)

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None

_PG_REPAIR_SHOP_USERS = """
CREATE TABLE IF NOT EXISTS repair_shop_users (
    id TEXT PRIMARY KEY,
    shop_id TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_PG_REPAIR_SHOP_CLAIM_ASSIGNMENTS = """
CREATE TABLE IF NOT EXISTS repair_shop_claim_assignments (
    id SERIAL PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES claims(id),
    shop_id TEXT NOT NULL,
    assigned_by TEXT,
    notes TEXT,
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(claim_id, shop_id)
)
"""


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute(REPAIR_SHOP_USERS_TABLE_SQLITE)
    else:
        op.execute(_PG_REPAIR_SHOP_USERS)
    op.execute(IDX_REPAIR_SHOP_USERS_EMAIL)
    op.execute(IDX_REPAIR_SHOP_USERS_SHOP_ID)

    if dialect == "sqlite":
        op.execute(REPAIR_SHOP_CLAIM_ASSIGNMENTS_TABLE_SQLITE)
    else:
        op.execute(_PG_REPAIR_SHOP_CLAIM_ASSIGNMENTS)
    op.execute(IDX_RSCA_CLAIM_ID)
    op.execute(IDX_RSCA_SHOP_ID)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS repair_shop_claim_assignments")
    op.execute("DROP TABLE IF EXISTS repair_shop_users")
