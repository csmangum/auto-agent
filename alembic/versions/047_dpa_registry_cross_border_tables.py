"""Add dpa_registry and cross_border_transfer_log tables for PostgreSQL deployments.

Revision ID: 047
Revises: 046
Create Date: 2026-03-22

The dpa_registry and cross_border_transfer_log tables are created by init_db() for
SQLite, but PostgreSQL deployments rely exclusively on Alembic migrations.  This
revision adds both tables (with indexes) for PostgreSQL, and is a no-op for SQLite
because the tables will already exist there.

Also adds the ``created_by`` column to ``dpa_registry`` (introduced to persist the
``actor_id`` audit field that was previously accepted but not stored).
"""

from alembic import op
from sqlalchemy import text


revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        # SQLite tables already exist via init_db().  Only add the new column if it
        # is absent (ALTER TABLE … ADD COLUMN is idempotent-safe via PRAGMA).
        existing_cols = {
            row[1]
            for row in conn.execute(text("PRAGMA table_info(dpa_registry)")).fetchall()
        }
        if "created_by" not in existing_cols:
            op.execute(text("ALTER TABLE dpa_registry ADD COLUMN created_by TEXT"))
        return

    # --- PostgreSQL -----------------------------------------------------------

    # dpa_registry
    op.execute(
        text("""
            CREATE TABLE IF NOT EXISTS dpa_registry (
                id SERIAL PRIMARY KEY,
                subprocessor_name TEXT NOT NULL,
                service_type TEXT NOT NULL,
                data_categories TEXT NOT NULL DEFAULT '[]',
                purpose TEXT NOT NULL,
                destination_country TEXT NOT NULL,
                destination_zone TEXT NOT NULL,
                mechanism TEXT NOT NULL,
                legal_basis TEXT,
                dpa_signed_date TEXT,
                dpa_expiry_date TEXT,
                dpa_document_ref TEXT,
                supplementary_measures TEXT DEFAULT '[]',
                active INTEGER NOT NULL DEFAULT 1,
                notes TEXT,
                created_by TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
        """)
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_dpa_registry_subprocessor "
            "ON dpa_registry(subprocessor_name)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_dpa_registry_active "
            "ON dpa_registry(active)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_dpa_registry_service_type "
            "ON dpa_registry(service_type)"
        )
    )

    # cross_border_transfer_log
    op.execute(
        text("""
            CREATE TABLE IF NOT EXISTS cross_border_transfer_log (
                id SERIAL PRIMARY KEY,
                claim_id TEXT,
                flow_name TEXT NOT NULL,
                source_zone TEXT NOT NULL,
                destination TEXT NOT NULL,
                destination_zone TEXT NOT NULL,
                data_categories TEXT NOT NULL DEFAULT '[]',
                mechanism TEXT NOT NULL,
                permitted INTEGER NOT NULL DEFAULT 1,
                policy_decision TEXT NOT NULL DEFAULT 'allow',
                notes TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
        """)
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_cbt_log_claim_id "
            "ON cross_border_transfer_log(claim_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_cbt_log_flow_name "
            "ON cross_border_transfer_log(flow_name)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_cbt_log_created_at "
            "ON cross_border_transfer_log(created_at)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_cbt_log_policy_decision "
            "ON cross_border_transfer_log(policy_decision)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        # SQLite doesn't support DROP COLUMN in older versions; skip.
        return

    # PostgreSQL
    op.execute(text("DROP INDEX IF EXISTS idx_cbt_log_policy_decision"))
    op.execute(text("DROP INDEX IF EXISTS idx_cbt_log_created_at"))
    op.execute(text("DROP INDEX IF EXISTS idx_cbt_log_flow_name"))
    op.execute(text("DROP INDEX IF EXISTS idx_cbt_log_claim_id"))
    op.execute(text("DROP TABLE IF EXISTS cross_border_transfer_log"))

    op.execute(text("DROP INDEX IF EXISTS idx_dpa_registry_service_type"))
    op.execute(text("DROP INDEX IF EXISTS idx_dpa_registry_active"))
    op.execute(text("DROP INDEX IF EXISTS idx_dpa_registry_subprocessor"))
    op.execute(text("DROP TABLE IF EXISTS dpa_registry"))
