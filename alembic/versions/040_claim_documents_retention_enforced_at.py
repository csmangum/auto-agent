"""claim_documents.retention_enforced_at for document retention job.

Revision ID: 040
Revises: 039
Create Date: 2026-03-21

GitHub issue #284: soft-archive documents past retention_date; index for eligibility scan.

Downgrade: On SQLite, only the partial index is dropped; the column is left in place
(SQLite lacks portable DROP COLUMN without a table rebuild on older versions). On
PostgreSQL, the column is dropped as well.
"""

from alembic import op
from sqlalchemy import text

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        cursor = conn.execute(text("PRAGMA table_info(claim_documents)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "retention_enforced_at" not in columns:
            op.execute(text("ALTER TABLE claim_documents ADD COLUMN retention_enforced_at TEXT"))
    else:
        op.execute(
            text(
                "ALTER TABLE claim_documents ADD COLUMN IF NOT EXISTS retention_enforced_at TEXT"
            )
        )

    if dialect == "sqlite":
        op.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_claim_documents_retention_eligible "
                "ON claim_documents(retention_date) "
                "WHERE retention_enforced_at IS NULL AND retention_date IS NOT NULL "
                "AND length(trim(retention_date)) > 0"
            )
        )
    else:
        op.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_claim_documents_retention_eligible "
                "ON claim_documents (retention_date) "
                "WHERE retention_enforced_at IS NULL AND retention_date IS NOT NULL "
                "AND length(trim(retention_date)) > 0"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    op.execute(text("DROP INDEX IF EXISTS idx_claim_documents_retention_eligible"))
    if conn.dialect.name == "sqlite":
        # See module docstring: column intentionally not dropped on SQLite.
        pass
    else:
        op.execute(text("ALTER TABLE claim_documents DROP COLUMN IF EXISTS retention_enforced_at"))
