"""Audit and history routes for claims: audit log, fraud filings, notes, and workflow runs."""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import ensure_claim_access_for_adjuster
from claim_agent.api.deps import require_role
from claim_agent.context import ClaimContext
from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.utils.sanitization import MAX_ACTOR_ID
from claim_agent.api.routes._claims_helpers import get_claim_context

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")


class AddNoteBody(BaseModel):
    note: str = Field(..., min_length=1, description="Note content")
    actor_id: str = Field(
        ...,
        min_length=1,
        max_length=MAX_ACTOR_ID,
        description="Crew name, agent identifier, or 'workflow'",
    )

    @field_validator("note", "actor_id", mode="after")
    @classmethod
    def strip_and_validate_not_blank(cls, v: str, info) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError(f"{info.field_name} cannot be blank")
        return stripped


@router.get("/claims/{claim_id}/history", dependencies=[RequireAdjuster])
def get_claim_history(
    claim_id: str,
    limit: int | None = Query(None, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get audit log entries for a claim with optional pagination.

    Omit ``limit`` (or pass no query param) to return the full history,
    preserving backwards-compatible behaviour for existing clients.
    """
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    history, total = ctx.repo.get_claim_history(claim_id, limit=limit, offset=offset)
    return {
        "claim_id": claim_id,
        "history": history,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/claims/{claim_id}/fraud-filings", dependencies=[RequireAdjuster])
def get_claim_fraud_filings(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get fraud report filings for a claim (state bureau, NICB, NISS) for compliance audit."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    filings = ctx.repo.get_fraud_filings_for_claim(claim_id)
    return {"claim_id": claim_id, "filings": filings}


@router.get("/claims/{claim_id}/notes", dependencies=[RequireAdjuster])
def get_claim_notes(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List notes for a claim, ordered by created_at."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    notes = ctx.repo.get_notes(claim_id)
    return {"claim_id": claim_id, "notes": notes}


@router.post("/claims/{claim_id}/notes", dependencies=[RequireAdjuster])
def add_claim_note(
    claim_id: str,
    body: AddNoteBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Add a note to a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    try:
        ctx.repo.add_note(claim_id, body.note, body.actor_id)
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    return {"claim_id": claim_id, "actor_id": body.actor_id}


@router.get("/claims/{claim_id}/workflows", dependencies=[RequireAdjuster])
def get_claim_workflows(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get workflow runs for a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT * FROM workflow_runs WHERE claim_id = :claim_id ORDER BY id ASC"),
            {"claim_id": claim_id},
        ).fetchall()

    return {"claim_id": claim_id, "workflows": [row_to_dict(r) for r in rows]}
