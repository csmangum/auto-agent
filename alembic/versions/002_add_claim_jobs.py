"""Add claim_jobs table for async queue tracking.

Revision ID: 002
Revises: 001
Create Date: 2026-03-06

"""
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_jobs (
            job_id TEXT PRIMARY KEY,
            claim_id TEXT NOT NULL,
            status TEXT DEFAULT 'queued',
            result_summary TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_jobs_claim_id ON claim_jobs(claim_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_claim_jobs_claim_id")
    op.execute("DROP TABLE IF EXISTS claim_jobs")
