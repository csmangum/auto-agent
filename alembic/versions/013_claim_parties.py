"""Add claim_parties table for claimant/policyholder identity management.

Revision ID: 013
Revises: 012
Create Date: 2026-03-16

Implements party identity tracking:
- claim_parties: claim_id, party_type, name, email, phone, role, represented_by_id,
  consent_status, authorization_status
- Party types: claimant, policyholder, witness, attorney, provider, lienholder
- represented_by_id: FK to claim_parties.id for attorney representation
"""
from alembic import op
from sqlalchemy import text


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute(text("""
        CREATE TABLE claim_parties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            party_type TEXT NOT NULL,
            name TEXT,
            email TEXT,
            phone TEXT,
            address TEXT,
            role TEXT,
            represented_by_id INTEGER,
            consent_status TEXT DEFAULT 'pending',
            authorization_status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id),
            FOREIGN KEY (represented_by_id) REFERENCES claim_parties(id)
        )
    """))
    op.execute(text(
        "CREATE INDEX idx_claim_parties_claim_id ON claim_parties(claim_id)"
    ))
    op.execute(text(
        "CREATE INDEX idx_claim_parties_claim_type ON claim_parties(claim_id, party_type)"
    ))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute(text("DROP INDEX IF EXISTS idx_claim_parties_claim_type"))
    op.execute(text("DROP INDEX IF EXISTS idx_claim_parties_claim_id"))
    op.execute(text("DROP TABLE IF EXISTS claim_parties"))
