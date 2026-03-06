"""Initial schema: claims, claim_audit_log, workflow_runs.

Revision ID: 001
Revises:
Create Date: 2025-03-05

"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS claims (
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
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS claim_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            action TEXT NOT NULL,
            old_status TEXT,
            new_status TEXT,
            details TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            claim_id TEXT NOT NULL,
            claim_type TEXT,
            router_output TEXT,
            workflow_output TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (claim_id) REFERENCES claims(id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_claims_incident_date")
    op.execute("DROP INDEX IF EXISTS idx_claims_vin")
    op.execute("DROP TABLE IF EXISTS workflow_runs")
    op.execute("DROP TABLE IF EXISTS claim_audit_log")
    op.execute("DROP TABLE IF EXISTS claims")
