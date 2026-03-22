"""Add dsar_verification_tokens table for OTP-based claimant identity proofing.

Revision ID: 046
Revises: 045
Create Date: 2026-03-22

Stores one-time password tokens used for self-service DSAR claimant verification:
- verification_id: UUID for tracking (returned to the claimant after requesting OTP)
- claimant_identifier: Email address or phone number supplied by the requester
- channel: 'email' or 'sms'
- token_hash: HMAC-SHA256 hash of the OTP (plaintext never stored)
- salt: Per-token random salt used for hashing
- expires_at: Token expiry timestamp (default TTL configured via OTP_TTL_MINUTES)
- verified_at: Timestamp set when the OTP is successfully verified; NULL means unverified
- attempts: Counter of failed verification attempts (locked after OTP_MAX_ATTEMPTS)
- created_at: Creation timestamp (used for rate-limit window queries)
"""

from alembic import op
from sqlalchemy import text


revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    dialect = conn.dialect.name

    if dialect == "sqlite":
        op.execute(
            text("""
                CREATE TABLE IF NOT EXISTS dsar_verification_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    verification_id TEXT NOT NULL UNIQUE,
                    claimant_identifier TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    verified_at TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
                )
            """)
        )
        op.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_dsar_verification_tokens_identifier "
                "ON dsar_verification_tokens(claimant_identifier, created_at)"
            )
        )
    else:
        op.execute(
            text("""
                CREATE TABLE IF NOT EXISTS dsar_verification_tokens (
                    id SERIAL PRIMARY KEY,
                    verification_id TEXT NOT NULL UNIQUE,
                    claimant_identifier TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    token_hash TEXT NOT NULL,
                    salt TEXT NOT NULL,
                    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
                    verified_at TIMESTAMP WITH TIME ZONE,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                )
            """)
        )
        op.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_dsar_verification_tokens_identifier "
                "ON dsar_verification_tokens(claimant_identifier, created_at)"
            )
        )


def downgrade() -> None:
    op.execute(
        text("DROP INDEX IF EXISTS idx_dsar_verification_tokens_identifier")
    )
    op.execute(text("DROP TABLE IF EXISTS dsar_verification_tokens"))
