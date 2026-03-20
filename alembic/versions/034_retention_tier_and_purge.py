"""Retention tier (active/cold/archived/purged) and purged_at for tiered retention.

Revision ID: 034
Revises: 033
Create Date: 2026-03-19
"""

from alembic import op
from sqlalchemy import text

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    retention_tier_added = False

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "retention_tier" not in columns:
            op.execute(
                text("ALTER TABLE claims ADD COLUMN retention_tier TEXT NOT NULL DEFAULT 'active'")
            )
            retention_tier_added = True
        if "purged_at" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN purged_at TEXT"))
    else:
        op.execute(
            text(
                "ALTER TABLE claims ADD COLUMN IF NOT EXISTS "
                "retention_tier TEXT NOT NULL DEFAULT 'active'"
            )
        )
        op.execute(text("ALTER TABLE claims ADD COLUMN IF NOT EXISTS purged_at TEXT"))

    if dialect != "sqlite" or retention_tier_added:
        op.execute(text("UPDATE claims SET retention_tier = 'archived' WHERE status = 'archived'"))
        op.execute(text("UPDATE claims SET retention_tier = 'cold' WHERE status = 'closed'"))


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        pass
    else:
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS purged_at"))
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS retention_tier"))
