"""Many-to-many claim party relationships; drop represented_by_id.

Revision ID: 036
Revises: 035
Create Date: 2026-03-20

Replaces claim_parties.represented_by_id with claim_party_relationships
(from_party_id, to_party_id, relationship_type).
"""
from alembic import op
from sqlalchemy import text

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute(
            text("""
                CREATE TABLE IF NOT EXISTS claim_party_relationships (
                    id SERIAL PRIMARY KEY,
                    from_party_id INTEGER NOT NULL REFERENCES claim_parties(id) ON DELETE CASCADE,
                    to_party_id INTEGER NOT NULL REFERENCES claim_parties(id) ON DELETE CASCADE,
                    relationship_type TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
        )
    else:
        op.execute(
            text("""
                CREATE TABLE IF NOT EXISTS claim_party_relationships (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    from_party_id INTEGER NOT NULL,
                    to_party_id INTEGER NOT NULL,
                    relationship_type TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now')),
                    FOREIGN KEY (from_party_id) REFERENCES claim_parties(id) ON DELETE CASCADE,
                    FOREIGN KEY (to_party_id) REFERENCES claim_parties(id) ON DELETE CASCADE
                )
            """)
        )

    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_from "
            "ON claim_party_relationships(from_party_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_to "
            "ON claim_party_relationships(to_party_id)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_claim_party_relationships_from_type "
            "ON claim_party_relationships(from_party_id, relationship_type)"
        )
    )

    cursor = conn.execute(text("PRAGMA table_info(claim_parties)")) if dialect == "sqlite" else None
    cols_sqlite = {row[1] for row in cursor.fetchall()} if cursor is not None else set()

    if dialect == "sqlite" and "represented_by_id" in cols_sqlite:
        op.execute(
            text("""
                INSERT INTO claim_party_relationships (from_party_id, to_party_id, relationship_type)
                SELECT id, represented_by_id, 'represented_by'
                FROM claim_parties
                WHERE represented_by_id IS NOT NULL
            """)
        )
        op.execute(text("ALTER TABLE claim_parties DROP COLUMN represented_by_id"))
    elif dialect == "postgresql":
        has_col = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = 'claim_parties' "
                "AND column_name = 'represented_by_id'"
            )
        ).scalar()
        if has_col:
            op.execute(
                text("""
                    INSERT INTO claim_party_relationships (from_party_id, to_party_id, relationship_type)
                    SELECT id, represented_by_id, 'represented_by'
                    FROM claim_parties
                    WHERE represented_by_id IS NOT NULL
                """)
            )
            op.execute(text("ALTER TABLE claim_parties DROP COLUMN IF EXISTS represented_by_id"))


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "postgresql":
        op.execute(
            text(
                "ALTER TABLE claim_parties ADD COLUMN IF NOT EXISTS "
                "represented_by_id INTEGER REFERENCES claim_parties(id)"
            )
        )
        op.execute(
            text("""
                UPDATE claim_parties cp
                SET represented_by_id = r.to_party_id
                FROM (
                    SELECT DISTINCT ON (from_party_id) from_party_id, to_party_id
                    FROM claim_party_relationships
                    WHERE relationship_type = 'represented_by'
                    ORDER BY from_party_id, id ASC
                ) r
                WHERE cp.id = r.from_party_id
            """)
        )
    else:
        cursor = conn.execute(text("PRAGMA table_info(claim_parties)"))
        cols = {row[1] for row in cursor.fetchall()}
        if "represented_by_id" not in cols:
            op.execute(
                text(
                    "ALTER TABLE claim_parties ADD COLUMN represented_by_id INTEGER "
                    "REFERENCES claim_parties(id)"
                )
            )
        op.execute(
            text("""
                UPDATE claim_parties SET represented_by_id = (
                    SELECT to_party_id FROM claim_party_relationships r
                    WHERE r.from_party_id = claim_parties.id
                      AND r.relationship_type = 'represented_by'
                    ORDER BY r.id ASC LIMIT 1
                )
            """)
        )

    op.execute(text("DROP INDEX IF EXISTS idx_claim_party_relationships_from_type"))
    op.execute(text("DROP INDEX IF EXISTS idx_claim_party_relationships_to"))
    op.execute(text("DROP INDEX IF EXISTS idx_claim_party_relationships_from"))
    op.execute(text("DROP TABLE IF EXISTS claim_party_relationships"))
