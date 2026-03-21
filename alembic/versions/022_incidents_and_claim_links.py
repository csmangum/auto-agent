"""Add incidents table and claim_links for multi-vehicle/multi-claimant support.

Revision ID: 022
Revises: 021
Create Date: 2026-03-17

Creates incident level above claims: one incident -> multiple claims.
- incidents: incident_date, incident_description, loss_state
- claims.incident_id: FK to incidents (nullable for backward compat)
- claim_links: links between related claims (same_incident, opposing_carrier, etc.)
"""
from alembic import op
from sqlalchemy import text

from claim_agent.db.schema_incidents_sqlite import (
    ALTER_CLAIMS_ADD_INCIDENT_ID_FK,
    CLAIM_LINKS_TABLE_SQLITE,
    INCIDENTS_TABLE_SQLITE,
    IDX_CLAIM_LINKS_CLAIM_A,
    IDX_CLAIM_LINKS_CLAIM_B,
    IDX_CLAIMS_INCIDENT_ID,
    IDX_INCIDENTS_INCIDENT_DATE,
)

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute(INCIDENTS_TABLE_SQLITE)
    op.execute(IDX_INCIDENTS_INCIDENT_DATE)

    # Add incident_id to claims (nullable for existing single-claim flow)
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "incident_id" not in columns:
        op.execute(text(ALTER_CLAIMS_ADD_INCIDENT_ID_FK))

    op.execute(CLAIM_LINKS_TABLE_SQLITE)
    op.execute(IDX_CLAIM_LINKS_CLAIM_A)
    op.execute(IDX_CLAIM_LINKS_CLAIM_B)
    op.execute(IDX_CLAIMS_INCIDENT_ID)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS idx_claims_incident_id")
    op.execute("DROP INDEX IF EXISTS idx_claim_links_claim_b")
    op.execute("DROP INDEX IF EXISTS idx_claim_links_claim_a")
    op.execute("DROP TABLE IF EXISTS claim_links")
    # SQLite does not support DROP COLUMN; leave incident_id in place
    op.execute("DROP INDEX IF EXISTS idx_incidents_incident_date")
    op.execute("DROP TABLE IF EXISTS incidents")
