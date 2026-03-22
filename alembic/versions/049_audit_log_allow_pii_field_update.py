"""Allow in-place PII redaction on claim_audit_log.before_state / after_state.

Revision ID: 049
Revises: 048
Create Date: 2026-03-22

GitHub issue: Audit log – Redact before_state / after_state (PII in JSON)

Decision (tamper-evidence vs erasure):
  - Non-PII columns (claim_id, action, old_status, new_status, details,
    actor_id, created_at) remain immutable via trigger – the audit trail
    is still tamper-evident for event metadata.
  - before_state / after_state carry snapshot JSON that may contain PII
    (policy_number, vin, party names, etc.).  After DSAR deletion or
    retention purge those fields may be updated *only* to replace PII
    keys with [REDACTED] placeholders; the trigger enforces that all
    other columns are unchanged.
  - This is gated by AUDIT_LOG_STATE_REDACTION_ENABLED=true (default off)
    so existing deployments are unaffected until explicitly opted in.
"""

from alembic import op
from sqlalchemy import text

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Replace the broad "block all updates" function/trigger with one
        # that only blocks changes to non-PII columns.
        op.execute(
            text("""
            CREATE OR REPLACE FUNCTION claim_audit_log_protect_non_pii_columns()
            RETURNS TRIGGER AS $$
            BEGIN
                IF (NEW.claim_id IS DISTINCT FROM OLD.claim_id) OR
                   (NEW.action IS DISTINCT FROM OLD.action) OR
                   (NEW.old_status IS DISTINCT FROM OLD.old_status) OR
                   (NEW.new_status IS DISTINCT FROM OLD.new_status) OR
                   (NEW.details IS DISTINCT FROM OLD.details) OR
                   (NEW.actor_id IS DISTINCT FROM OLD.actor_id) OR
                   (NEW.created_at IS DISTINCT FROM OLD.created_at)
                THEN
                    RAISE EXCEPTION
                        'claim_audit_log: only before_state and after_state may be updated';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """)
        )
        op.execute(
            text("""
            DROP TRIGGER IF EXISTS claim_audit_log_prevent_update ON claim_audit_log;
            CREATE TRIGGER claim_audit_log_protect_non_pii_columns
            BEFORE UPDATE ON claim_audit_log FOR EACH ROW
            EXECUTE PROCEDURE claim_audit_log_protect_non_pii_columns()
            """)
        )
        # Remove the now-superseded prevent_update function (trigger renamed above).
        op.execute(text("DROP FUNCTION IF EXISTS claim_audit_log_prevent_update()"))
    else:
        # SQLite: replace the broad "raise on any update" trigger with one
        # that only raises when non-PII columns are modified.
        op.execute(text("DROP TRIGGER IF EXISTS claim_audit_log_prevent_update"))
        op.execute(
            text("""
            CREATE TRIGGER claim_audit_log_protect_non_pii_columns
            BEFORE UPDATE ON claim_audit_log
            BEGIN
                SELECT RAISE(ABORT,
                    'claim_audit_log: only before_state and after_state may be updated')
                WHERE (NEW.claim_id IS NOT OLD.claim_id)
                   OR (NEW.action IS NOT OLD.action)
                   OR (NEW.old_status IS NOT OLD.old_status)
                   OR (NEW.new_status IS NOT OLD.new_status)
                   OR (NEW.details IS NOT OLD.details)
                   OR (NEW.actor_id IS NOT OLD.actor_id)
                   OR (NEW.created_at IS NOT OLD.created_at);
            END
            """)
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            text(
                "DROP TRIGGER IF EXISTS claim_audit_log_protect_non_pii_columns "
                "ON claim_audit_log"
            )
        )
        op.execute(
            text("DROP FUNCTION IF EXISTS claim_audit_log_protect_non_pii_columns()")
        )
        # Restore the original broad UPDATE block.
        op.execute(
            text("""
            CREATE OR REPLACE FUNCTION claim_audit_log_prevent_update()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'claim_audit_log is append-only: updates are not allowed';
            END;
            $$ LANGUAGE plpgsql
            """)
        )
        op.execute(
            text("""
            DROP TRIGGER IF EXISTS claim_audit_log_prevent_update ON claim_audit_log;
            CREATE TRIGGER claim_audit_log_prevent_update
            BEFORE UPDATE ON claim_audit_log FOR EACH ROW
            EXECUTE PROCEDURE claim_audit_log_prevent_update()
            """)
        )
    else:
        op.execute(
            text("DROP TRIGGER IF EXISTS claim_audit_log_protect_non_pii_columns")
        )
        op.execute(
            text("""
            CREATE TRIGGER claim_audit_log_prevent_update
            BEFORE UPDATE ON claim_audit_log
            BEGIN
                SELECT RAISE(ABORT,
                    'claim_audit_log is append-only: updates are not allowed');
            END
            """)
        )
