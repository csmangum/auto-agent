"""Add reserve management: reserve_amount on claims, reserve_history table.

Revision ID: 010
Revises: 009
Create Date: 2026-03-15

Implements reserve management per system-assessment.md:
- reserve_amount: estimated ultimate cost carrier sets aside
- reserve_history: append-only audit of reserve changes

Downgrade note: _downgrade_recreate_claims() hardcodes the claims schema.
If a later migration adds columns to claims, this downgrade will fail because
claims_new omits those columns. Downgrades are best-effort for SQLite; consider
running migrations forward-only in production.
"""
from alembic import op
from sqlalchemy import text


revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "reserve_amount" not in columns:
        op.execute(text("ALTER TABLE claims ADD COLUMN reserve_amount REAL"))

    tables = {
        row[0]
        for row in conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        ).fetchall()
    }
    if "reserve_history" not in tables:
        op.execute(text("""
            CREATE TABLE reserve_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                claim_id TEXT NOT NULL,
                old_amount REAL,
                new_amount REAL NOT NULL,
                reason TEXT DEFAULT '',
                actor_id TEXT DEFAULT 'workflow',
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (claim_id) REFERENCES claims(id)
            )
        """))
        op.execute(text("""
            CREATE TRIGGER reserve_history_prevent_update
            BEFORE UPDATE ON reserve_history
            BEGIN
                SELECT RAISE(ABORT, 'reserve_history is append-only: updates are not allowed');
            END
        """))
        op.execute(text("""
            CREATE TRIGGER reserve_history_prevent_delete
            BEFORE DELETE ON reserve_history
            BEGIN
                SELECT RAISE(ABORT, 'reserve_history is append-only: deletes are not allowed');
            END
        """))
        op.execute(text(
            "CREATE INDEX idx_reserve_history_claim_id ON reserve_history(claim_id)"
        ))


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        return
    op.execute(text("DROP INDEX IF EXISTS idx_reserve_history_claim_id"))
    op.execute(text("DROP TRIGGER IF EXISTS reserve_history_prevent_delete"))
    op.execute(text("DROP TRIGGER IF EXISTS reserve_history_prevent_update"))
    op.execute(text("DROP TABLE IF EXISTS reserve_history"))

    conn = op.get_bind()
    cursor = conn.execute(text("PRAGMA table_info(claims)"))
    columns = {row[1] for row in cursor.fetchall()}
    if "reserve_amount" in columns:
        op.execute(text("PRAGMA foreign_keys = OFF"))
        try:
            _downgrade_recreate_claims()
        finally:
            op.execute(text("PRAGMA foreign_keys = ON"))


def _downgrade_recreate_claims() -> None:
    """Recreate claims table without reserve_amount. Schema is fixed at revision 010."""
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
            siu_case_id TEXT,
            archived_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """))
    op.execute(text("""
        INSERT INTO claims_new
        (id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
         incident_date, incident_description, damage_description, estimated_damage,
         claim_type, status, payout_amount, attachments, assignee,
         review_started_at, review_notes, due_at, priority, siu_case_id, archived_at,
         created_at, updated_at)
        SELECT id, policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
               incident_date, incident_description, damage_description, estimated_damage,
               claim_type, status, payout_amount, attachments, assignee,
               review_started_at, review_notes, due_at, priority, siu_case_id, archived_at,
               created_at, updated_at
        FROM claims
    """))
    op.execute(text("DROP TABLE claims"))
    op.execute(text("ALTER TABLE claims_new RENAME TO claims"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_claims_vin ON claims(vin)"))
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_claims_incident_date ON claims(incident_date)"))
