"""Add claim_payments table for payment/disbursement workflow.

Revision ID: 011
Revises: 010
Create Date: 2026-03-16

Implements payment issuance, approval, and disbursement tracking:
- amount, payee, payee_type, payment_method, check_number, status, authorized_by
- Two-party check support (payee_secondary for lienholder + insured)
- Payment status: authorized -> issued -> cleared/voided
"""
from alembic import op
from sqlalchemy import text


revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE claim_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            amount REAL NOT NULL,
            payee TEXT NOT NULL,
            payee_type TEXT NOT NULL,
            payment_method TEXT NOT NULL,
            check_number TEXT,
            status TEXT NOT NULL DEFAULT 'authorized',
            authorized_by TEXT NOT NULL,
            issued_at TEXT,
            cleared_at TEXT,
            voided_at TEXT,
            void_reason TEXT,
            payee_secondary TEXT,
            payee_secondary_type TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """))
    op.execute(text(
        "CREATE INDEX idx_claim_payments_claim_id ON claim_payments(claim_id)"
    ))
    op.execute(text(
        "CREATE INDEX idx_claim_payments_status ON claim_payments(status)"
    ))


def downgrade() -> None:
    op.execute(text("DROP INDEX IF EXISTS idx_claim_payments_status"))
    op.execute(text("DROP INDEX IF EXISTS idx_claim_payments_claim_id"))
    op.execute(text("DROP TABLE IF EXISTS claim_payments"))
