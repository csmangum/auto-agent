"""Adjuster scoping: claim assignee must match authenticated identity for role adjuster."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from claim_agent.api.auth import AuthContext
from claim_agent.db.repository import ClaimRepository


def adjuster_identity_scopes_assignee(auth: AuthContext) -> bool:
    """True when adjuster should filter list/stats/review-queue by claims.assignee."""
    if auth.role != "adjuster":
        return False
    return not auth.identity.startswith("key-")


def claim_not_visible_to_adjuster(auth: AuthContext, claim_row: dict[str, Any]) -> bool:
    if auth.role != "adjuster":
        return False
    # API key without key:role:user_id uses hashed identity (key-…); no assignee scoping (legacy).
    if auth.identity.startswith("key-"):
        return False
    return (claim_row.get("assignee") or "") != auth.identity


def ensure_claim_access_for_adjuster(
    auth: AuthContext, claim_id: str, row: dict[str, Any] | None
) -> dict[str, Any]:
    """404 if claim missing or adjuster cannot access (assignee must match identity)."""
    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    if claim_not_visible_to_adjuster(auth, row):
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    return row


def filter_related_claim_ids_for_adjuster(
    auth: AuthContext,
    claim_repo: ClaimRepository,
    related_ids: list[str],
) -> list[str]:
    """Return only related claim IDs the adjuster may see."""
    if auth.role != "adjuster":
        return related_ids
    out: list[str] = []
    for cid in related_ids:
        row = claim_repo.get_claim(cid)
        if row is not None and not claim_not_visible_to_adjuster(auth, row):
            out.append(cid)
    return out
