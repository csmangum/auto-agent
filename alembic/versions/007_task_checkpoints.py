"""Add task_checkpoints table for resumable workflows.

Revision ID: 007
Revises: 006
Create Date: 2026-03-07

Implements GitHub issue #70: Resumable Workflows and Checkpointing
- task_checkpoints: per-stage checkpoint storage so reprocess can resume
  from the last successful stage instead of re-running from scratch.
"""
from alembic import op
from sqlalchemy import text


revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    tables = {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    }
    if "task_checkpoints" not in tables:
        op.execute(text("""
            CREATE TABLE task_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                workflow_run_id TEXT NOT NULL,
                stage_key TEXT NOT NULL,
                output TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id),
                UNIQUE(claim_id, workflow_run_id, stage_key)
            )
        """))
    # Ensure index exists even if table was created via SCHEMA_SQL
    indexes = {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='task_checkpoints'")
        ).fetchall()
    }
    if "idx_task_checkpoints_claim_run" not in indexes:
        op.execute(text("""
            CREATE INDEX idx_task_checkpoints_claim_run
                ON task_checkpoints(claim_id, workflow_run_id)
        """))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_task_checkpoints_claim_run"))
    op.execute(text("DROP TABLE IF EXISTS task_checkpoints"))
