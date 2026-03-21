"""Add optional incident_latitude and incident_longitude to claims.

Revision ID: 043
Revises: 042
Create Date: 2026-03-21

Optional WGS84 coordinates for FNOL (best-effort geocode) for fraud photo GPS checks.

PostgreSQL: ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` requires PostgreSQL 9.1+.

SQLite downgrade: ``downgrade()`` is a no-op on SQLite. Dropping columns was not supported
before SQLite 3.35.0 (March 2021); a rebuild migration would be needed to remove these
columns on older embedded SQLite builds. Leaving columns avoids destructive downgrade.
"""
from alembic import op
from sqlalchemy import text


revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "incident_latitude" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN incident_latitude REAL"))
        if "incident_longitude" not in columns:
            op.execute(text("ALTER TABLE claims ADD COLUMN incident_longitude REAL"))
    else:
        # IF NOT EXISTS: PostgreSQL 9.1+
        op.execute(
            text("ALTER TABLE claims ADD COLUMN IF NOT EXISTS incident_latitude DOUBLE PRECISION")
        )
        op.execute(
            text("ALTER TABLE claims ADD COLUMN IF NOT EXISTS incident_longitude DOUBLE PRECISION")
        )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        # See module docstring: no DROP COLUMN on SQLite here (version / rebuild constraints).
        return
    else:
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS incident_longitude"))
        op.execute(text("ALTER TABLE claims DROP COLUMN IF EXISTS incident_latitude"))
