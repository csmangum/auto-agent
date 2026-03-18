"""Add litigation_hold to claims and support DSAR deletion.

Revision ID: 029
Revises: 028
Create Date: 2026-03-18

litigation_hold: When set, blocks DSAR purge/anonymization for that claim.
"""
from alembic import op
from sqlalchemy import text

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "litigation_hold" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN litigation_hold INTEGER DEFAULT 0"))
    else:
        op.execute(text("ALTER TABLE claims ADD COLUMN IF NOT EXISTS litigation_hold INTEGER DEFAULT 0"))


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "sqlite":
        # SQLite does not support DROP COLUMN easily; leave litigation_hold in place.
        pass
    else:
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS litigation_hold"))
