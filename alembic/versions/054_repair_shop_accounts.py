"""Add repair_shop_users and repair_shop_claim_assignments for multi-claim portal accounts.

Revision ID: 054
Revises: 053

Repair shop user accounts (shop_id, email, password) allow a shop to authenticate
once and view all assigned claims rather than juggling one per-claim magic token
per repair order.  The repair_shop_claim_assignments table records explicit
claim ↔ shop pairings with an audit trail (assigned_by, assigned_at).

Backward-compatible: existing repair_shop_access_tokens (per-claim tokens) are
not altered.
"""

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    # ------------------------------------------------------------------
    # repair_shop_users
    # ------------------------------------------------------------------
    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS repair_shop_users (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS repair_shop_users (
                id TEXT PRIMARY KEY,
                shop_id TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repair_shop_users_email ON repair_shop_users(email)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repair_shop_users_shop_id ON repair_shop_users(shop_id)"
    )

    # ------------------------------------------------------------------
    # repair_shop_claim_assignments
    # ------------------------------------------------------------------
    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS repair_shop_claim_assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                shop_id TEXT NOT NULL,
                assigned_by TEXT,
                notes TEXT,
                assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id),
                UNIQUE(claim_id, shop_id)
            )
        """)
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS repair_shop_claim_assignments (
                id SERIAL PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(id),
                shop_id TEXT NOT NULL,
                assigned_by TEXT,
                notes TEXT,
                assigned_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(claim_id, shop_id)
            )
        """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repair_shop_assignments_claim_id "
        "ON repair_shop_claim_assignments(claim_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_repair_shop_assignments_shop_id "
        "ON repair_shop_claim_assignments(shop_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS repair_shop_claim_assignments")
    op.execute("DROP TABLE IF EXISTS repair_shop_users")
