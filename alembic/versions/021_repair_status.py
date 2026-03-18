"""Add repair_status table for partial loss repair progress tracking.

Revision ID: 021
Revises: 020
Create Date: 2026-03-17

Tracks repair progress: received -> disassembly -> parts_ordered -> repair ->
paint -> reassembly -> qa -> ready. Shops POST status updates via webhook.
"""
from alembic import op


revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute("""
        CREATE TABLE IF NOT EXISTS repair_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            shop_id TEXT NOT NULL,
            authorization_id TEXT,
            status TEXT NOT NULL,
            status_updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            notes TEXT,
            paused_at TEXT,
            pause_reason TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_repair_status_claim_id ON repair_status(claim_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_repair_status_shop_status ON repair_status(shop_id, status)")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS idx_repair_status_shop_status")
    op.execute("DROP INDEX IF EXISTS idx_repair_status_claim_id")
    op.execute("DROP TABLE IF EXISTS repair_status")
