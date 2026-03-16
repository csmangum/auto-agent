"""Add subrogation_cases table for recovery and arbitration tracking.

Revision ID: 015
Revises: 014
Create Date: 2026-03-16

Adds subrogation_cases table for:
- Case tracking (case_id, amount_sought, opposing_carrier)
- Arbitration status (arbitration_status, arbitration_forum, dispute_date)
- Liability metadata (liability_percentage, liability_basis)
"""
from alembic import op
from sqlalchemy import text


revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE IF NOT EXISTS subrogation_cases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            case_id TEXT NOT NULL UNIQUE,
            amount_sought REAL NOT NULL,
            opposing_carrier TEXT,
            status TEXT DEFAULT 'pending',
            arbitration_status TEXT,
            arbitration_forum TEXT,
            dispute_date TEXT,
            liability_percentage REAL,
            liability_basis TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """))
    op.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_subrogation_cases_claim_id ON subrogation_cases(claim_id)"
    ))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_subrogation_cases_claim_id"))
    op.execute(text("DROP TABLE IF EXISTS subrogation_cases"))
