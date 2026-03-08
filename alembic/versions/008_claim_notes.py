"""Add claim_notes table for cross-crew communication.

Revision ID: 008
Revises: 007
Create Date: 2026-03-08

Implements GitHub issue #131: Claim notes system for agents and crews.
- claim_notes: append-only notes from workflow, crews, or agents
"""
from alembic import op
from sqlalchemy import text


revision = "008"
down_revision = "007"
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
    if "claim_notes" not in tables:
        op.execute(text("""
            CREATE TABLE claim_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                note TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            )
        """))
    indexes = {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='claim_notes'")
        ).fetchall()
    }
    if "idx_claim_notes_claim_id" not in indexes:
        op.execute(text("""
            CREATE INDEX idx_claim_notes_claim_id ON claim_notes(claim_id)
        """))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_claim_notes_claim_id"))
    op.execute(text("DROP TABLE IF EXISTS claim_notes"))
