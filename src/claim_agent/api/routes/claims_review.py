"""Review workflow routes for claims: assign, acknowledge, approve, reject, request-info, escalate, review."""

import asyncio
import math
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import ensure_claim_access_for_adjuster
from claim_agent.api.deps import require_role
from claim_agent.context import ClaimContext
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.constants import STATUS_NEEDS_REVIEW
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.claim import ClaimInput
from claim_agent.utils.sanitization import MAX_PAYOUT
from claim_agent.workflow.claim_review_orchestrator import run_claim_review as run_claim_review_workflow
from claim_agent.workflow.handback_orchestrator import run_handback_workflow

from claim_agent.api.routes._claims_helpers import (
    get_approve_lock as _get_approve_lock,
    get_claim_context,
)

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")
RequireSupervisor = require_role("supervisor", "admin", "executive")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class AssignBody(BaseModel):
    assignee: str = Field(..., min_length=1, description="Adjuster/user ID to assign")


class RejectBody(BaseModel):
    reason: str = ""


class RequestInfoBody(BaseModel):
    note: str = ""


class ReviewerDecisionBody(BaseModel):
    """Optional reviewer decision for handback when approving a claim."""

    confirmed_claim_type: Optional[
        Literal["new", "duplicate", "total_loss", "partial_loss", "bodily_injury", "fraud"]
    ] = Field(
        default=None,
        description="Reviewer-confirmed claim type. Must be one of: new, duplicate, total_loss, partial_loss, bodily_injury, fraud.",
    )
    confirmed_payout: Optional[float] = Field(
        default=None,
        description="Reviewer-confirmed payout amount",
    )
    notes: Optional[str] = Field(default=None, description="Reviewer notes")

    @field_validator("confirmed_payout")
    @classmethod
    def validate_payout(cls, v: Optional[float]) -> Optional[float]:
        """Reject NaN, inf, negative, or excessive payout amounts."""
        if v is None:
            return v
        if not math.isfinite(v):
            raise ValueError("confirmed_payout cannot be NaN or infinite")
        if v < 0:
            raise ValueError("confirmed_payout must be non-negative")
        if v > MAX_PAYOUT:
            raise ValueError(f"confirmed_payout must be <= {MAX_PAYOUT:,.0f}")
        return v


class ApproveBody(BaseModel):
    """Optional body for approve endpoint to pass reviewer decision for handback."""

    reviewer_decision: Optional[ReviewerDecisionBody] = Field(
        default=None,
        description="Reviewer decision for handback processing",
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.patch("/claims/{claim_id}/assign")
def assign_claim(
    claim_id: str,
    body: AssignBody = Body(...),
    auth: AuthContext = RequireSupervisor,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Assign claim to an adjuster."""
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.adjuster_service.assign(claim_id, body.assignee, actor_id=actor_id)
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "assignee": body.assignee}


@router.post("/claims/{claim_id}/acknowledge")
def acknowledge_claim(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Record UCSPA claim acknowledgment (receipt acknowledged within state deadline)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.repo.record_acknowledgment(claim_id, actor_id=actor_id)
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from e
    return {"claim_id": claim_id, "acknowledged": True}


@router.post("/claims/{claim_id}/review/approve")
async def approve_review(
    claim_id: str,
    body: ApproveBody = Body(default=ApproveBody()),
    auth: AuthContext = RequireSupervisor,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Approve claim for continued processing. Runs Human Review Handback crew to parse
    reviewer decision, update claim, then routes to next step (settlement, subrogation, etc).
    Requires supervisor.

    Uses a per-claim lock to prevent concurrent approve requests from racing. In multi-process
    deployments, use a distributed lock (e.g. Redis) instead.
    """
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    if claim.get("status") != STATUS_NEEDS_REVIEW:
        raise HTTPException(
            status_code=409,
            detail=f"Claim {claim_id} is not in needs_review (status={claim.get('status')}); cannot approve.",
        )

    lock = await _get_approve_lock(claim_id)
    async with lock:
        claim = await asyncio.to_thread(ctx.repo.get_claim, claim_id)
        if claim is None:
            raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
        if claim.get("status") != STATUS_NEEDS_REVIEW:
            raise HTTPException(
                status_code=409,
                detail=f"Claim {claim_id} is not in needs_review (status={claim.get('status')}); already processed.",
            )
        claim_data = claim_data_from_row(claim)
        try:
            ClaimInput.model_validate(claim_data)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=f"Invalid claim data for reprocess: {e}") from e
        actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
        try:
            await asyncio.to_thread(ctx.adjuster_service.approve, claim_id, actor_id=actor_id)
        except ClaimNotFoundError as e:
            raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from e
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        reviewer_decision = None
        if body.reviewer_decision:
            reviewer_decision = {
                "confirmed_claim_type": body.reviewer_decision.confirmed_claim_type,
                "confirmed_payout": body.reviewer_decision.confirmed_payout,
                "notes": body.reviewer_decision.notes,
            }

        result = await asyncio.to_thread(
            run_handback_workflow,
            claim_id,
            reviewer_decision=reviewer_decision,
            actor_id=actor_id,
            ctx=ctx,
        )
    return result


@router.post("/claims/{claim_id}/review/reject")
def reject_review(
    claim_id: str,
    body: RejectBody = Body(default=RejectBody()),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Reject claim with optional reason."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.adjuster_service.reject(claim_id, actor_id=actor_id, reason=body.reason)
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "status": "denied"}


@router.post("/claims/{claim_id}/review/request-info")
def request_info_review(
    claim_id: str,
    body: RequestInfoBody = Body(default=RequestInfoBody()),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Request more information from claimant."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.adjuster_service.request_info(claim_id, actor_id=actor_id, note=body.note)
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "status": "pending_info"}


@router.post("/claims/{claim_id}/review/escalate-to-siu")
def escalate_to_siu(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Escalate claim to Special Investigations Unit."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.adjuster_service.escalate_to_siu(claim_id, actor_id=actor_id)
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "status": "under_investigation"}


@router.post("/claims/{claim_id}/review")
async def run_claim_review(
    claim_id: str,
    auth: AuthContext = RequireSupervisor,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Run supervisor/compliance review on the claim process. Requires supervisor role.

    Returns a ClaimReviewReport with issues, compliance_checks, and recommendations.
    The report is persisted to the audit log.
    """
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    actor_id = auth.identity if auth.identity != "anonymous" else "claim_review_crew"
    report = await asyncio.to_thread(
        run_claim_review_workflow,
        claim_id,
        actor_id=actor_id,
        ctx=ctx,
    )

    report_json = report.model_dump_json()
    ctx.repo.record_claim_review(claim_id, report_json, actor_id)

    return report.model_dump(mode="json")
