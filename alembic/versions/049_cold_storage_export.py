"""Add cold_storage_exported_at and cold_storage_export_key to claims.

Revision ID: 049
Revises: 048

These columns track idempotent S3/Glacier cold-storage exports written before
or instead of in-place retention purge (see ``claim-agent retention-export``).
"""

from alembic import op
from sqlalchemy import text

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        existing_cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(claims)")).fetchall()
        }
        if "cold_storage_exported_at" not in existing_cols:
            conn.execute(
                text("ALTER TABLE claims ADD COLUMN cold_storage_exported_at TEXT")
            )
        if "cold_storage_export_key" not in existing_cols:
            conn.execute(
                text("ALTER TABLE claims ADD COLUMN cold_storage_export_key TEXT")
            )
    else:
        # PostgreSQL
        exists_exported_at = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='claims' AND column_name='cold_storage_exported_at'"
            ),
        ).fetchone()
        if not exists_exported_at:
            op.execute(
                text("ALTER TABLE claims ADD COLUMN cold_storage_exported_at TIMESTAMPTZ")
            )
        exists_export_key = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='claims' AND column_name='cold_storage_export_key'"
            ),
        ).fetchone()
        if not exists_export_key:
            op.execute(text("ALTER TABLE claims ADD COLUMN cold_storage_export_key TEXT"))


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect != "sqlite":
        conn.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS cold_storage_exported_at"))
        conn.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS cold_storage_export_key"))
    # SQLite does not support DROP COLUMN portably; leave columns in place on downgrade.
