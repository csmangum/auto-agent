"""Claimant portal access verification.

Verifies that a claimant has access to a claim via:
- token: claim_id + claim_access_token (hashed)
- policy_vin: claim_id + policy_number + vin
- email: claim_id + email (matches claim_parties when DSAR_VERIFICATION_REQUIRED=false)
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from sqlalchemy import text

from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, row_to_dict

logger = logging.getLogger(__name__)


@dataclass
class ClaimantContext:
    """Verified claimant identity and claim access."""

    claim_id: str
    identity: str  # email, party_id, or token prefix for audit


def _hash_token(token: str) -> str:
    """SHA-256 hash of token for storage comparison."""
    return hashlib.sha256(token.encode()).hexdigest()


def verify_claimant_access(
    claim_id: str,
    *,
    token: str | None = None,
    policy_number: str | None = None,
    vin: str | None = None,
    email: str | None = None,
    db_path: str | None = None,
) -> ClaimantContext | None:
    """Verify claimant has access to the claim. Returns ClaimantContext or None.

    Uses CLAIMANT_VERIFICATION_MODE to determine which verification to apply.
    """
    settings = get_settings()
    if not settings.portal.enabled:
        return None

    mode = settings.portal.verification_mode
    path = db_path or get_db_path()

    with get_connection(path) as conn:
        # First verify claim exists
        row = conn.execute(
            text("SELECT id, policy_number, vin FROM claims WHERE id = :claim_id"),
            {"claim_id": claim_id},
        ).fetchone()
        if row is None:
            return None
        claim = row_to_dict(row)

        if mode == "token":
            if not token or not token.strip():
                return None
            token_hash = _hash_token(token.strip())
            now = datetime.now(timezone.utc).isoformat()
            row = conn.execute(
                text("""
                    SELECT claim_id, party_id, email FROM claim_access_tokens
                    WHERE claim_id = :claim_id AND token_hash = :token_hash
                    AND expires_at > :now
                """),
                {
                    "claim_id": claim_id,
                    "token_hash": token_hash,
                    "now": now,
                },
            ).fetchone()
            if row is None:
                return None
            rec = row_to_dict(row)
            identity = rec.get("email") or f"party-{rec.get('party_id')}" or "token"
            return ClaimantContext(claim_id=claim_id, identity=str(identity))

        if mode == "policy_vin":
            if not policy_number or not vin:
                return None
            pn = str(policy_number).strip()
            v = str(vin).strip()
            if claim.get("policy_number") == pn and claim.get("vin") == v:
                return ClaimantContext(
                    claim_id=claim_id,
                    identity=f"policy:{pn[:4]}***",
                )
            return None

        if mode == "email":
            if not email or not email.strip():
                return None
            if not settings.privacy.dsar_verification_required:
                row = conn.execute(
                    text("""
                        SELECT 1 FROM claim_parties
                        WHERE claim_id = :claim_id AND email = :email
                    """),
                    {"claim_id": claim_id, "email": email.strip()},
                ).fetchone()
                if row is not None:
                    return ClaimantContext(claim_id=claim_id, identity=email.strip())
            return None

    return None


def create_claim_access_token(
    claim_id: str,
    *,
    party_id: int | None = None,
    email: str | None = None,
    db_path: str | None = None,
) -> str:
    """Create a claim access token and return the raw token (to send to claimant).

    Caller must store/send the returned token; it is not stored in plaintext.
    """
    raw_token = secrets.token_urlsafe(32)
    token_hash = _hash_token(raw_token)
    settings = get_settings()
    expiry_days = settings.portal.token_expiry_days
    expires_at = (datetime.now(timezone.utc) + timedelta(days=expiry_days)).isoformat()

    path = db_path or get_db_path()
    with get_connection(path) as conn:
        conn.execute(
            text("""
                INSERT INTO claim_access_tokens
                (claim_id, token_hash, party_id, email, expires_at)
                VALUES (:claim_id, :token_hash, :party_id, :email, :expires_at)
            """),
            {
                "claim_id": claim_id,
                "token_hash": token_hash,
                "party_id": party_id,
                "email": email,
                "expires_at": expires_at,
            },
        )
        conn.commit()

    logger.info("Created claim access token for claim_id=%s", claim_id)
    return raw_token


def get_claim_ids_for_claimant(
    *,
    token: str | None = None,
    policy_number: str | None = None,
    vin: str | None = None,
    email: str | None = None,
    db_path: str | None = None,
) -> list[str]:
    """Get list of claim IDs the claimant can access (for listing claims).

    Uses CLAIMANT_VERIFICATION_MODE to determine which verification method(s) to accept.
    Only the configured mode is honored; other credentials are ignored.
    """
    settings = get_settings()
    if not settings.portal.enabled:
        return []

    mode = settings.portal.verification_mode
    path = db_path or get_db_path()
    seen: set[str] = set()

    with get_connection(path) as conn:
        if mode == "token" and token and token.strip():
            token_hash = _hash_token(token.strip())
            now = datetime.now(timezone.utc).isoformat()
            rows = conn.execute(
                text("""
                    SELECT claim_id FROM claim_access_tokens
                    WHERE token_hash = :token_hash AND expires_at > :now
                """),
                {"token_hash": token_hash, "now": now},
            ).fetchall()
            for r in rows:
                cid = str(r[0]) if hasattr(r, "__getitem__") else str(r["claim_id"])
                seen.add(cid)

        if mode == "policy_vin" and policy_number and vin:
            pn = str(policy_number).strip()
            v = str(vin).strip()
            rows = conn.execute(
                text("""
                    SELECT id FROM claims
                    WHERE policy_number = :pn AND vin = :vin
                """),
                {"pn": pn, "vin": v},
            ).fetchall()
            for r in rows:
                cid = str(r[0]) if hasattr(r, "__getitem__") else str(r["id"])
                seen.add(cid)

        if (
            mode == "email"
            and email
            and email.strip()
            and not settings.privacy.dsar_verification_required
        ):
            rows = conn.execute(
                text("""
                    SELECT DISTINCT claim_id FROM claim_parties
                    WHERE email = :email
                """),
                {"email": email.strip()},
            ).fetchall()
            for r in rows:
                cid = str(r[0]) if hasattr(r, "__getitem__") else str(r["claim_id"])
                seen.add(cid)

    return list(seen)
