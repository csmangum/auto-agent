"""Add topic column to follow_up_messages table.

Revision ID: 057
Revises: 056
Create Date: 2026-03-24

Implements GitHub issue #471 / follow-up: surface rental-related follow-up
messages on the Rental tab.  Adds an optional `topic` column so messages can
be tagged (e.g. 'rental') for targeted display in the claimant portal.
"""
from alembic import op
from sqlalchemy import text


revision = "057"
down_revision = "056"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            text(
                "ALTER TABLE follow_up_messages ADD COLUMN IF NOT EXISTS topic TEXT"
            )
        )
    else:
        # SQLite – check whether column already exists before adding it
        columns = {
            row[1]
            for row in conn.execute(
                text("PRAGMA table_info(follow_up_messages)")
            ).fetchall()
        }
        if "topic" not in columns:
            conn.execute(
                text("ALTER TABLE follow_up_messages ADD COLUMN topic TEXT")
            )


def downgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == "postgresql":
        conn.execute(
            text("ALTER TABLE follow_up_messages DROP COLUMN IF EXISTS topic")
        )
    # SQLite does not support DROP COLUMN in older versions; downgrade is a no-op.
