"""Financial operation routes for claims: reserves, litigation hold, repair status."""

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import ensure_claim_access_for_adjuster
from claim_agent.api.deps import require_role
from claim_agent.context import ClaimContext
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.constants import VALID_REPAIR_STATUSES
from claim_agent.db.database import get_db_path
from claim_agent.db.repair_status_repository import RepairStatusRepository
from claim_agent.exceptions import ClaimNotFoundError, ReserveAuthorityError
from claim_agent.tools.partial_loss_logic import _parse_partial_loss_workflow_output
from claim_agent.api.routes._claims_helpers import get_claim_context

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")


class ReserveBody(BaseModel):
    """Request body for PATCH /claims/{claim_id}/reserve."""

    reserve_amount: float = Field(..., ge=0, description="New reserve amount in dollars")
    reason: str = Field(default="", max_length=500, description="Reason for change")
    skip_authority_check: bool = Field(
        default=False,
        description="If true, bypass reserve authority limits (admin role only).",
    )


class LitigationHoldBody(BaseModel):
    """Request body for PATCH /claims/{claim_id}/litigation-hold."""

    litigation_hold: bool = Field(..., description="True to set hold, False to clear")


class RepairStatusUpdateBody(BaseModel):
    """Request body for updating repair status (simulation/dashboard)."""

    status: str = Field(..., min_length=1, max_length=64)
    shop_id: str | None = Field(default=None, max_length=128)
    authorization_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


@router.patch("/claims/{claim_id}/litigation-hold", dependencies=[RequireAdjuster])
def patch_claim_litigation_hold(
    claim_id: str,
    body: LitigationHoldBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Set or clear litigation hold. Claims with hold are excluded from retention and DSAR deletion."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.repo.set_litigation_hold(claim_id, body.litigation_hold, actor_id=actor_id)
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    return {"claim_id": claim_id, "litigation_hold": body.litigation_hold}


@router.patch("/claims/{claim_id}/reserve", dependencies=[RequireAdjuster])
def patch_claim_reserve(
    claim_id: str,
    body: ReserveBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Set or adjust reserve amount for a claim. Uses adjust_reserve (handles initial set)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    skip = body.skip_authority_check
    if skip and auth.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="skip_authority_check is only allowed for the admin role.",
        )
    try:
        ctx.repo.adjust_reserve(
            claim_id,
            body.reserve_amount,
            reason=body.reason,
            actor_id=actor_id,
            role=auth.role,
            skip_authority_check=skip and auth.role == "admin",
        )
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    except ReserveAuthorityError as e:
        raise HTTPException(
            status_code=403,
            detail=str(e),
        ) from e
    return {"claim_id": claim_id, "reserve_amount": body.reserve_amount}


@router.get("/claims/{claim_id}/reserve-history", dependencies=[RequireAdjuster])
def get_claim_reserve_history(
    claim_id: str,
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get reserve history for a claim, most recent first."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    history = ctx.repo.get_reserve_history(claim_id, limit=limit)
    return {"claim_id": claim_id, "history": history, "limit": limit}


@router.get("/claims/{claim_id}/reserve/adequacy", dependencies=[RequireAdjuster])
def get_claim_reserve_adequacy(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Check reserve adequacy vs estimated_damage and payout_amount.

    Response includes ``warnings`` (human text) and ``warning_codes`` (stable ``RESERVE_*`` strings).
    """
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    try:
        result = ctx.repo.check_reserve_adequacy(claim_id)
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    return result


@router.get("/claims/{claim_id}/repair-status", dependencies=[RequireAdjuster])
def get_claim_repair_status(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get repair status and history for a partial loss claim."""
    claim_row = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    if claim_row.get("claim_type") != "partial_loss":
        raise HTTPException(
            status_code=400,
            detail="Repair status only applies to partial_loss claims",
        )
    repo = RepairStatusRepository(db_path=get_db_path())
    latest = repo.get_repair_status(claim_id)
    history = repo.get_repair_status_history(claim_id)
    cycle_time_days = repo.get_cycle_time_days(claim_id)
    return {
        "claim_id": claim_id,
        "latest": latest,
        "history": history,
        "cycle_time_days": cycle_time_days,
    }


@router.post("/claims/{claim_id}/repair-status", dependencies=[RequireAdjuster])
def update_claim_repair_status(
    claim_id: str,
    body: RepairStatusUpdateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Update repair status (for simulation/dashboard). Infers shop_id from workflow if omitted."""
    if body.status not in VALID_REPAIR_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(VALID_REPAIR_STATUSES)}",
        )
    claim_repo = ctx.repo
    claim = ensure_claim_access_for_adjuster(auth, claim_id, claim_repo.get_claim(claim_id))
    if claim.get("claim_type") != "partial_loss":
        raise HTTPException(
            status_code=400,
            detail="Repair status only applies to partial_loss claims",
        )
    shop_id = body.shop_id
    auth_id = body.authorization_id
    if not shop_id or not auth_id:
        runs = claim_repo.get_workflow_runs(claim_id, limit=5)
        for run in runs:
            if run.get("claim_type") != "partial_loss":
                continue
            parsed = _parse_partial_loss_workflow_output(run.get("workflow_output") or "")
            if parsed:
                shop_id = shop_id or str(parsed.get("shop_id", "")).strip()
                auth_id = auth_id or str(parsed.get("authorization_id", "")).strip()
                break
    if not shop_id:
        shop_id = "unknown"
    status_repo = RepairStatusRepository(db_path=get_db_path())
    row_id = status_repo.insert_repair_status(
        claim_id=claim_id,
        shop_id=shop_id,
        status=body.status,
        authorization_id=auth_id,
        notes=body.notes,
    )
    return {"ok": True, "repair_status_id": row_id}
