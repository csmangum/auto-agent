"""Audit trail enhancements: actor_id, before_state, after_state.

Revision ID: 002
Revises: 001
Create Date: 2026-03-06

Implements GitHub issue #54: Audit Trail Enhancements
- actor_id: who performed the action (system/workflow/adjuster_id)
- before_state, after_state: JSON for critical field changes
- Append-only: no UPDATE/DELETE on claim_audit_log
"""
from alembic import op
from sqlalchemy import text


revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def _columns_exist(conn, table: str) -> set[str]:
    """Return set of column names for table.

    Note: table must be a trusted identifier (hardcoded). Do not pass
    user-controlled input; PRAGMA table_info does not support parameterization.
    """
    cursor = conn.execute(text(f"PRAGMA table_info({table})"))
    return {row[1] for row in cursor.fetchall()}


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    conn = op.get_bind()
    existing = _columns_exist(conn, "claim_audit_log")
    if "actor_id" not in existing:
        op.execute(text("ALTER TABLE claim_audit_log ADD COLUMN actor_id TEXT DEFAULT 'system'"))
    if "before_state" not in existing:
        op.execute(text("ALTER TABLE claim_audit_log ADD COLUMN before_state TEXT"))
    if "after_state" not in existing:
        op.execute(text("ALTER TABLE claim_audit_log ADD COLUMN after_state TEXT"))
    # Enforce append-only behavior: prevent UPDATE and DELETE on claim_audit_log
    op.execute(text("DROP TRIGGER IF EXISTS claim_audit_log_prevent_update"))
    op.execute(text("DROP TRIGGER IF EXISTS claim_audit_log_prevent_delete"))
    # Backfill actor_id for existing rows
    op.execute(text("UPDATE claim_audit_log SET actor_id = 'system' WHERE actor_id IS NULL"))
    op.execute(text("""
        CREATE TRIGGER claim_audit_log_prevent_update
        BEFORE UPDATE ON claim_audit_log
        BEGIN
            SELECT RAISE(ABORT, 'claim_audit_log is append-only: updates are not allowed');
        END;
    """))
    op.execute(text("""
        CREATE TRIGGER claim_audit_log_prevent_delete
        BEFORE DELETE ON claim_audit_log
        BEGIN
            SELECT RAISE(ABORT, 'claim_audit_log is append-only: deletes are not allowed');
        END;
    """))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    # Drop append-only triggers before table recreation
    op.execute(text("DROP TRIGGER IF EXISTS claim_audit_log_prevent_update"))
    op.execute(text("DROP TRIGGER IF EXISTS claim_audit_log_prevent_delete"))
    # SQLite does not support DROP COLUMN until 3.35.0. Recreate table.
    op.execute(text("""
        CREATE TABLE claim_audit_log_old (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            action TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """))
    op.execute(text("""
        INSERT INTO claim_audit_log_old
        (id, claim_id, action, old_status, new_status, details, created_at)
        SELECT id, claim_id, action, old_status, new_status, details, created_at
        FROM claim_audit_log
    """))
    op.execute(text("DROP TABLE claim_audit_log"))
    op.execute(text("ALTER TABLE claim_audit_log_old RENAME TO claim_audit_log"))
