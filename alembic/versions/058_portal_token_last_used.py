"""Add last_used_at column to portal token tables for inactivity timeout.

Revision ID: 058
Revises: 057
Create Date: 2026-03-26

Adds a ``last_used_at`` column to all four portal token tables so that an
inactivity timeout can be enforced: if a token has not been used within
``CLAIM_PORTAL_INACTIVITY_TIMEOUT_DAYS`` (default 30) the verification
function will reject it even if the absolute ``expires_at`` is still in the
future.

Tables updated:
- claim_access_tokens       (claimant portal)
- repair_shop_access_tokens (repair shop per-claim tokens)
- third_party_access_tokens (third-party / TPA tokens)
- external_portal_tokens    (unified role-bearing portal tokens)
"""

from alembic import op
from sqlalchemy import text

revision = "058"
down_revision = "057"
branch_labels = None
depends_on = None

# Tables and column to add
_TABLES = [
    "claim_access_tokens",
    "repair_shop_access_tokens",
    "third_party_access_tokens",
    "external_portal_tokens",
]


def _add_column_sqlite(conn, table: str) -> None:
    """Add last_used_at to *table* on SQLite (check first to be idempotent)."""
    columns = {
        row[1]
        for row in conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    }
    if "last_used_at" not in columns:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN last_used_at TEXT"))


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for table in _TABLES:
            conn.execute(
                text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS"
                    " last_used_at TIMESTAMPTZ"
                )
            )
    else:
        for table in _TABLES:
            _add_column_sqlite(conn, table)


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        for table in _TABLES:
            conn.execute(
                text(f"ALTER TABLE {table} DROP COLUMN IF EXISTS last_used_at")
            )
    # SQLite does not support DROP COLUMN in older versions; downgrade is a no-op.
