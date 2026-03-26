"""Claimant portal access verification.

Verifies that a claimant has access to a claim via:
- token: claim_id + claim_access_token (hashed)
- policy_vin: claim_id + policy_number + vin
- email: claim_id + email (matches claim_parties when DSAR_VERIFICATION_REQUIRED=false)
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from claim_agent.config import get_settings
from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.services.portal_token_utils import (
    hash_portal_token,
    portal_token_last_used_rejects,
)

logger = logging.getLogger(__name__)


@dataclass
class ClaimantContext:
    """Verified claimant identity and claim access."""

    claim_id: str
    identity: str  # email, party_id, or token prefix for audit


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
    Token-based verification also enforces an inactivity timeout: tokens not
    used within ``CLAIM_PORTAL_INACTIVITY_TIMEOUT_DAYS`` days are rejected.
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
            token_hash = hash_portal_token(token.strip())
            now = datetime.now(timezone.utc)
            inactivity_cutoff = now - timedelta(
                days=settings.portal.inactivity_timeout_days
            )
            row = conn.execute(
                text("""
                    SELECT id, claim_id, party_id, email, last_used_at
                    FROM claim_access_tokens
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
            if portal_token_last_used_rejects(
                rec.get("last_used_at"),
                inactivity_cutoff,
                logger=logger,
                inactive_log="Rejecting inactive claimant token for claim_id=%s",
                inactive_args=(claim_id,),
                token_id=rec.get("id"),
            ):
                return None
            # Update last_used_at
            conn.execute(
                text("""
                    UPDATE claim_access_tokens
                    SET last_used_at = :now
                    WHERE id = :token_id
                """),
                {"now": now, "token_id": rec["id"]},
            )
            conn.commit()
            party_id = rec.get("party_id")
            identity = (
                rec.get("email")
                or (f"party-{party_id}" if party_id is not None else None)
                or "token"
            )
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
    token_hash = hash_portal_token(raw_token)
    settings = get_settings()
    expiry_days = settings.portal.token_expiry_days
    expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days)

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
    Token-based lookups also enforce an inactivity timeout and update last_used_at.
    """
    settings = get_settings()
    if not settings.portal.enabled:
        return []

    mode = settings.portal.verification_mode
    path = db_path or get_db_path()
    seen: set[str] = set()

    with get_connection(path) as conn:
        if mode == "token" and token and token.strip():
            token_hash = hash_portal_token(token.strip())
            now = datetime.now(timezone.utc)
            inactivity_cutoff = now - timedelta(
                days=settings.portal.inactivity_timeout_days
            )
            rows = conn.execute(
                text("""
                    SELECT id, claim_id, last_used_at FROM claim_access_tokens
                    WHERE token_hash = :token_hash AND expires_at > :now
                """),
                {"token_hash": token_hash, "now": now},
            ).fetchall()
            active_ids: list[int] = []
            for r in rows:
                rec = row_to_dict(r)
                if portal_token_last_used_rejects(
                    rec.get("last_used_at"),
                    inactivity_cutoff,
                    logger=logger,
                    inactive_log=None,
                    inactive_args=(),
                    token_id=rec.get("id"),
                ):
                    continue
                cid = str(rec["claim_id"])
                seen.add(cid)
                active_ids.append(int(rec["id"]))
            # Bulk-update last_used_at for all active matching rows
            if active_ids:
                id_placeholders = ", ".join(f":id_{i}" for i in range(len(active_ids)))
                params: dict[str, object] = {"now": now}
                for i, tid in enumerate(active_ids):
                    params[f"id_{i}"] = tid
                conn.execute(
                    text(
                        "UPDATE claim_access_tokens SET last_used_at = :now "
                        f"WHERE id IN ({id_placeholders})"
                    ),
                    params,
                )
                conn.commit()

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
