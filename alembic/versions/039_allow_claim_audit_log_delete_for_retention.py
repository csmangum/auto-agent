"""Allow DELETE on claim_audit_log for gated audit retention purge.

Revision ID: 039
Revises: 038
Create Date: 2026-03-21

GitHub issue #350: append-only UPDATE remains; DELETE trigger removed so
claim-agent audit-log-purge can remove rows after export and compliance approval.
"""

from alembic import op
from sqlalchemy import text

revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            text("DROP TRIGGER IF EXISTS claim_audit_log_prevent_delete ON claim_audit_log")
        )
        op.execute(text("DROP FUNCTION IF EXISTS claim_audit_log_prevent_delete()"))
    else:
        op.execute(text("DROP TRIGGER IF EXISTS claim_audit_log_prevent_delete"))


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            text("""
            CREATE OR REPLACE FUNCTION claim_audit_log_prevent_delete()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'claim_audit_log is append-only: deletes are not allowed';
            END;
            $$ LANGUAGE plpgsql
            """)
        )
        op.execute(
            text("""
            DROP TRIGGER IF EXISTS claim_audit_log_prevent_delete ON claim_audit_log;
            CREATE TRIGGER claim_audit_log_prevent_delete
            BEFORE DELETE ON claim_audit_log FOR EACH ROW
            EXECUTE PROCEDURE claim_audit_log_prevent_delete()
            """)
        )
    else:
        op.execute(
            text("""
            CREATE TRIGGER claim_audit_log_prevent_delete
            BEFORE DELETE ON claim_audit_log
            BEGIN
                SELECT RAISE(ABORT, 'claim_audit_log is append-only: deletes are not allowed');
            END;
            """)
        )
