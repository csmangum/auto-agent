"""Add review queue columns to claims for human-in-the-loop workflow.

Revision ID: 005
Revises: 004
Create Date: 2026-03-06

Implements GitHub issue #61: Human-in-the-Loop Review Queue and Adjuster Workflow
- assignee: adjuster/user ID
- review_started_at: when claim entered needs_review
- review_notes: adjuster notes
- due_at: SLA target datetime (ISO)
- priority: critical | high | medium | low
"""
from alembic import op
from sqlalchemy import text


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None

NEW_COLUMNS = [
    ("assignee", "TEXT"),
    ("review_started_at", "TEXT"),
    ("review_notes", "TEXT"),
    ("due_at", "TEXT"),
    ("priority", "TEXT"),
]


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    for col_name, col_type in NEW_COLUMNS:
        if col_name not in columns:
            op.execute(text(f"ALTER TABLE claims ADD COLUMN {col_name} {col_type}"))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute(text("PRAGMA foreign_keys = OFF"))
    try:
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
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """))
    op.execute(text("""
        INSERT INTO claims_new
        (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
         incident_date, incident_description, damage_description, estimated_damage,
         claim_type, status, payout_amount, attachments, created_at, updated_at)
        SELECT id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
               incident_date, incident_description, damage_description, estimated_damage,
               claim_type, status, payout_amount, attachments, created_at, updated_at
        FROM claims
    """))
    op.execute(text("DROP TABLE claims"))
    op.execute(text("ALTER TABLE claims_new RENAME TO claims"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin)"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date)"))
