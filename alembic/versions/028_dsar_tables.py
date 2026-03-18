"""Add dsar_requests and dsar_exports tables for privacy compliance.

Revision ID: 028
Revises: 027
Create Date: 2026-03-18

Data Subject Access Request (DSAR) workflow: access and deletion requests
with audit trail for CCPA/state privacy law compliance.
"""
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute("""
            CREATE TABLE IF NOT EXISTS dsar_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL UNIQUE,
                claimant_identifier TEXT NOT NULL,
                request_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at TEXT,
                actor_id TEXT,
                notes TEXT,
                verification_data TEXT
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_requests_request_id ON dsar_requests(request_id)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_requests_status ON dsar_requests(status)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_requests_claimant ON dsar_requests(claimant_identifier)")

        op.execute("""
            CREATE TABLE IF NOT EXISTS dsar_exports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                request_id TEXT NOT NULL,
                export_path TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (request_id) REFERENCES dsar_requests(request_id)
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_exports_request_id ON dsar_exports(request_id)")
    else:
        op.execute("""
            CREATE TABLE IF NOT EXISTS dsar_requests (
                id SERIAL PRIMARY KEY,
                request_id TEXT NOT NULL UNIQUE,
                claimant_identifier TEXT NOT NULL,
                request_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                actor_id TEXT,
                notes TEXT,
                verification_data TEXT
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_requests_request_id ON dsar_requests(request_id)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_requests_status ON dsar_requests(status)")
        op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_requests_claimant ON dsar_requests(claimant_identifier)")

        op.execute("""
            CREATE TABLE IF NOT EXISTS dsar_exports (
                id SERIAL PRIMARY KEY,
                request_id TEXT NOT NULL,
                export_path TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (request_id) REFERENCES dsar_requests(request_id)
            )
        """)
        op.execute("CREATE INDEX IF NOT EXISTS idx_dsar_exports_request_id ON dsar_exports(request_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dsar_exports")
    op.execute("DROP TABLE IF EXISTS dsar_requests")
