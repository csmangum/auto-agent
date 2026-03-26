"""SQLite DDL for fraud_report_filings (SIU / compliance audit).

Aligned with alembic/versions/027_fraud_report_filings.py. Included in
``database.SCHEMA_SQL`` so fresh SQLite databases (tests, temp DBs) match
stamped head without running incremental migrations.
"""

FRAUD_REPORT_FILINGS_TABLE_SQLITE = """CREATE TABLE IF NOT EXISTS fraud_report_filings (
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
)"""

IDX_FRAUD_FILINGS_CLAIM_ID = (
    "CREATE INDEX IF NOT EXISTS idx_fraud_filings_claim_id ON fraud_report_filings(claim_id)"
)

IDX_FRAUD_FILINGS_FILING_TYPE = (
    "CREATE INDEX IF NOT EXISTS idx_fraud_filings_filing_type ON fraud_report_filings(filing_type)"
)
