"""Add diary system: recurrence, escalation, auto_created_from on claim_tasks.

Revision ID: 020
Revises: 019
Create Date: 2026-03-17

Implements Calendar/Diary System:
- recurrence_rule: daily | interval_days | weekly | null
- recurrence_interval: integer (e.g. 3 for every 3 days)
- parent_task_id: link recurring instances to parent
- escalation_level: 0=normal, 1=notified, 2=escalated
- escalation_notified_at: when overdue notification sent
- escalation_escalated_at: when escalated to supervisor
- auto_created_from: e.g. status_transition:processing
"""
from alembic import op
from sqlalchemy import text


revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
    if "claim_tasks" not in tables:
        return

    cursor = conn.execute(text("PRAGMA table_info(claim_tasks)"))
    columns = {row[1] for row in cursor.fetchall()}

    new_cols = [
        ("recurrence_rule", "TEXT"),
        ("recurrence_interval", "INTEGER"),
        ("parent_task_id", "INTEGER REFERENCES claim_tasks(id)"),
        ("escalation_level", "INTEGER NOT NULL DEFAULT 0"),
        ("escalation_notified_at", "TEXT"),
        ("escalation_escalated_at", "TEXT"),
        ("auto_created_from", "TEXT"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in columns:
            op.execute(text(f"ALTER TABLE claim_tasks ADD COLUMN {col_name} {col_type}"))

    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_claim_tasks_due_date "
        "ON claim_tasks(due_date) WHERE due_date IS NOT NULL AND status NOT IN ('completed', 'cancelled')"
    ))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_claim_tasks_parent_task "
        "ON claim_tasks(parent_task_id) WHERE parent_task_id IS NOT NULL"
    ))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
    if "claim_tasks" not in tables:
        return

    op.execute(text("DROP INDEX IF EXISTS idx_claim_tasks_parent_task"))
    op.execute(text("DROP INDEX IF EXISTS idx_claim_tasks_due_date"))

    cursor = conn.execute(text("PRAGMA table_info(claim_tasks)"))
    columns = {row[1] for row in cursor.fetchall()}
    drop_cols = [
        "recurrence_rule", "recurrence_interval", "parent_task_id",
        "escalation_level", "escalation_notified_at", "escalation_escalated_at",
        "auto_created_from",
    ]
    if any(c in columns for c in drop_cols):
        # SQLite doesn't support DROP COLUMN easily; recreate table without new cols
        op.execute(text("""
            CREATE TABLE claim_tasks_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                title TEXT NOT NULL,
                task_type TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'medium',
                assigned_to TEXT,
                created_by TEXT NOT NULL DEFAULT 'workflow',
                due_date TEXT,
                resolution_notes TEXT,
                document_request_id INTEGER,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id),
                FOREIGN KEY (document_request_id) REFERENCES document_requests(id)
            )
        """))
        op.execute(text("""
            INSERT INTO claim_tasks_new
            (id, claim_id, title, task_type, description, status, priority,
             assigned_to, created_by, due_date, resolution_notes, document_request_id,
             created_at, updated_at)
            SELECT id, claim_id, title, task_type, description, status, priority,
                   assigned_to, created_by, due_date, resolution_notes, document_request_id,
                   created_at, updated_at
            FROM claim_tasks
        """))
        op.execute(text("DROP TABLE claim_tasks"))
        op.execute(text("ALTER TABLE claim_tasks_new RENAME TO claim_tasks"))
        op.execute(text("CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_id ON claim_tasks(claim_id)"))
        op.execute(text("CREATE INDEX IF NOT EXISTS idx_claim_tasks_status ON claim_tasks(status)"))
        op.execute(text("CREATE INDEX IF NOT EXISTS idx_claim_tasks_claim_status ON claim_tasks(claim_id, status)"))
