"""Add incidents table and claim_links for multi-vehicle/multi-claimant support.

Revision ID: 022
Revises: 021
Create Date: 2026-03-17

Creates incident level above claims: one incident -> multiple claims.
- incidents: incident_date, incident_description, loss_state
- claims.incident_id: FK to incidents (nullable for backward compat)
- claim_links: links between related claims (same_incident, opposing_carrier, etc.)
"""
from alembic import op
from sqlalchemy import text


revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS incidents (
            id TEXT PRIMARY KEY,
            incident_date TEXT NOT NULL,
            incident_description TEXT,
            loss_state TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_incidents_incident_date ON incidents(incident_date)")

    # Add incident_id to claims (nullable for existing single-claim flow)
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "incident_id" not in columns:
        op.execute(text("ALTER TABLE claims ADD COLUMN incident_id TEXT REFERENCES incidents(id)"))

    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id_a TEXT NOT NULL,
            claim_id_b TEXT NOT NULL,
            link_type TEXT NOT NULL,
            opposing_carrier TEXT,
            notes TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id_a) REFERENCES claims(id),
            FOREIGN KEY (claim_id_b) REFERENCES claims(id),
            UNIQUE (claim_id_a, claim_id_b, link_type)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_links_claim_a ON claim_links(claim_id_a)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claim_links_claim_b ON claim_links(claim_id_b)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claims_incident_id ON claims(incident_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_claims_incident_id")
    op.execute("DROP INDEX IF EXISTS idx_claim_links_claim_b")
    op.execute("DROP INDEX IF EXISTS idx_claim_links_claim_a")
    op.execute("DROP TABLE IF EXISTS claim_links")
    # SQLite does not support DROP COLUMN; leave incident_id in place
    op.execute("DROP INDEX IF EXISTS idx_incidents_incident_date")
    op.execute("DROP TABLE IF EXISTS incidents")
