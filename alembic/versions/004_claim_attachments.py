"""Add attachments column to claims for document/photo metadata.

Revision ID: 004
Revises: 003
Create Date: 2026-03-06

Implements GitHub issue #56: Document and Photo Handling
- attachments: JSON array of {url, type, description} per attachment
"""
from alembic import op
from sqlalchemy import text


revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "attachments" not in columns:
        op.execute(text(
            "ALTER TABLE claims ADD COLUMN attachments TEXT DEFAULT '[]'"
        ))


def downgrade() -> None:
    # SQLite does not support DROP COLUMN easily; recreate table
    op.execute(text("""
        CREATE TABLE claims_new (
            id TEXT PRIMARY KEY,
            policy_number TEXT NOT NULL,
            vin TEXT NOT NULL,
            vehicle_year INTEGER,
            vehicle_make TEXT,
            vehicle_model TEXT,
            incident_date TEXT,
            incident_description TEXT,
            damage_description TEXT,
            estimated_damage REAL,
            claim_type TEXT,
            status TEXT DEFAULT 'pending',
            payout_amount REAL,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """))
    op.execute(text("""
        INSERT INTO claims_new
        (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
         incident_date, incident_description, damage_description, estimated_damage,
         claim_type, status, payout_amount, created_at, updated_at)
        SELECT id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
               incident_date, incident_description, damage_description, estimated_damage,
               claim_type, status, payout_amount, created_at, updated_at
        FROM claims
    """))
    op.execute(text("DROP TABLE claims"))
    op.execute(text("ALTER TABLE claims_new RENAME TO claims"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin)"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date)"))
