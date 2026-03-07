"""Add siu_case_id column to claims for SIU integration.

Revision ID: 006
Revises: 005
Create Date: 2026-03-06

Implements GitHub issue #72: SIU Integration
- siu_case_id: SIU case identifier when fraud workflow creates a referral
"""
from alembic import op
from sqlalchemy import text


revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "siu_case_id" not in columns:
        op.execute(text("ALTER TABLE claims ADD COLUMN siu_case_id TEXT"))


def downgrade() -> None:
    op.execute(text("PRAGMA foreign_keys = OFF"))
    try:
        conn = op.get_bind()
        cursor = conn.execute(text("PRAGMA table_info(claims)"))
        columns = {row[1] for row in cursor.fetchall()}
        if "siu_case_id" in columns:
            _downgrade_recreate_claims()
    finally:
        op.execute(text("PRAGMA foreign_keys = ON"))


def _downgrade_recreate_claims() -> None:
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
            attachments TEXT DEFAULT '[]',
            assignee TEXT,
            review_started_at TEXT,
            review_notes TEXT,
            due_at TEXT,
            priority TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """))
    op.execute(text("""
        INSERT INTO claims_new
        (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
         incident_date, incident_description, damage_description, estimated_damage,
         claim_type, status, payout_amount, attachments, assignee,
         review_started_at, review_notes, due_at, priority, created_at, updated_at)
        SELECT id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
               incident_date, incident_description, damage_description, estimated_damage,
               claim_type, status, payout_amount, attachments, assignee,
               review_started_at, review_notes, due_at, priority, created_at, updated_at
        FROM claims
    """))
    op.execute(text("DROP TABLE claims"))
    op.execute(text("ALTER TABLE claims_new RENAME TO claims"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin)"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date)"))
