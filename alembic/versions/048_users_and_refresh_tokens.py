"""Add users and refresh_tokens for Auth Phase 2.

Revision ID: 048
Revises: 047

SQLite: tables are created by init_db() / SCHEMA_SQL for new databases; this
revision adds them for existing SQLite files when Alembic is run.
PostgreSQL: creates both tables with indexes.
"""

from alembic import op
from sqlalchemy import text

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        existing = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
                    "('users', 'refresh_tokens')"
                )
            ).fetchall()
        }
        if "users" not in existing:
            op.execute(
                text("""
                    CREATE TABLE users (
                        id TEXT PRIMARY KEY,
                        email TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        role TEXT NOT NULL,
                        is_active INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT (datetime('now')),
                        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
            )
            op.execute(text("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"))
        if "refresh_tokens" not in existing:
            op.execute(
                text("""
                    CREATE TABLE refresh_tokens (
                        id TEXT PRIMARY KEY,
                        user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                        token_hash TEXT NOT NULL,
                        expires_at TEXT NOT NULL,
                        revoked_at TEXT,
                        replaced_by TEXT,
                        created_at TEXT NOT NULL DEFAULT (datetime('now'))
                    )
                """)
            )
            op.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id "
                    "ON refresh_tokens(user_id)"
                )
            )
            op.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash "
                    "ON refresh_tokens(token_hash)"
                )
            )
            op.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at "
                    "ON refresh_tokens(expires_at)"
                )
            )
        return

    op.execute(
        text("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
        """)
    )
    op.execute(text("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)"))

    op.execute(
        text("""
            CREATE TABLE IF NOT EXISTS refresh_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                token_hash TEXT NOT NULL,
                expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                revoked_at TIMESTAMP WITH TIME ZONE,
                replaced_by TEXT,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
            )
        """)
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user_id "
            "ON refresh_tokens(user_id)"
        )
    )
    op.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_tokens_token_hash "
            "ON refresh_tokens(token_hash)"
        )
    )
    op.execute(
        text(
            "CREATE INDEX IF NOT EXISTS idx_refresh_tokens_expires_at "
            "ON refresh_tokens(expires_at)"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute(text("DROP TABLE IF EXISTS refresh_tokens"))
        op.execute(text("DROP TABLE IF EXISTS users"))
        return

    op.execute(text("DROP INDEX IF EXISTS idx_refresh_tokens_expires_at"))
    op.execute(text("DROP INDEX IF EXISTS idx_refresh_tokens_token_hash"))
    op.execute(text("DROP INDEX IF EXISTS idx_refresh_tokens_user_id"))
    op.execute(text("DROP TABLE IF EXISTS refresh_tokens"))
    op.execute(text("DROP INDEX IF EXISTS idx_users_email"))
    op.execute(text("DROP TABLE IF EXISTS users"))
