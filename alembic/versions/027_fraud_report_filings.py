"""Add fraud_report_filings table for fraud reporting compliance audit.

Revision ID: 027
Revises: 026
Create Date: 2026-03-18

Tracks state bureau, NICB, and NISS fraud report filings for compliance
auditing and mandatory reporting enforcement.
"""
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS fraud_report_filings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                siu_case_id TEXT,
                filing_type TEXT NOT NULL,
                state TEXT,
                report_id TEXT NOT NULL,
                filed_at TEXT NOT NULL,
                filed_by TEXT NOT NULL DEFAULT 'siu_crew',
                indicators_count INTEGER DEFAULT 0,
                template_version TEXT,
                metadata TEXT,
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_fraud_filings_claim_id ON fraud_report_filings(claim_id)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_fraud_filings_filing_type ON fraud_report_filings(filing_type)")
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS fraud_report_filings (
                id SERIAL PRIMARY KEY,
                claim_id TEXT NOT NULL REFERENCES claims(id),
                siu_case_id TEXT,
                filing_type TEXT NOT NULL,
                state TEXT,
                report_id TEXT NOT NULL,
                filed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                filed_by TEXT NOT NULL DEFAULT 'siu_crew',
                indicators_count INTEGER DEFAULT 0,
                template_version TEXT,
                metadata TEXT
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_fraud_filings_claim_id ON fraud_report_filings(claim_id)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_fraud_filings_filing_type ON fraud_report_filings(filing_type)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_fraud_filings_filing_type")
    op.execute("DROP INDEX IF EXISTS idx_fraud_filings_claim_id")
    op.execute("DROP TABLE IF EXISTS fraud_report_filings")
