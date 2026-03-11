"""Add follow_up_messages table for human-in-the-loop flows.

Revision ID: 009
Revises: 008
Create Date: 2026-03-11

Implements GitHub issue #185: User Types and Follow-up Agent.
- follow_up_messages: outreach and responses for structured user interactions
"""
from alembic import op
from sqlalchemy import text


revision = "009"
down_revision = "008"
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
    if "follow_up_messages" not in tables:
        op.execute(text("""
            CREATE TABLE follow_up_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                user_type TEXT NOT NULL,
                message_content TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                response_content TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                responded_at TEXT,
                actor_id TEXT DEFAULT 'workflow',
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            )
        """))
    indexes = {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='follow_up_messages'")
        ).fetchall()
    }
    if "idx_follow_up_messages_claim_id" not in indexes:
        op.execute(text("""
            CREATE INDEX idx_follow_up_messages_claim_id ON follow_up_messages(claim_id)
        """))
    if "idx_follow_up_messages_status" not in indexes:
        op.execute(text("""
            CREATE INDEX idx_follow_up_messages_status ON follow_up_messages(claim_id, status)
        """))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_follow_up_messages_status"))
    op.execute(text("DROP INDEX IF EXISTS idx_follow_up_messages_claim_id"))
    op.execute(text("DROP TABLE IF EXISTS follow_up_messages"))
