"""Specialized workflow routes for claims: follow-up, SIU, disputes, denials, and supplemental."""

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import ensure_claim_access_for_adjuster
from claim_agent.api.deps import RequireAdjuster
from claim_agent.context import ClaimContext
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.constants import (
    DENIAL_COVERAGE_STATUSES,
    DISPUTABLE_STATUSES,
    SIU_INVESTIGATION_STATUSES,
)
from claim_agent.exceptions import (
    ClaimNotFoundError,
    DomainValidationError,
    FollowUpMessageNotFoundError,
)
from claim_agent.models.dispute import DisputeType
from claim_agent.rag.constants import normalize_state
from claim_agent.services.supplemental_request import execute_supplemental_request
from claim_agent.utils.sanitization import (
    MAX_DENIAL_REASON,
    MAX_DISPUTE_DESCRIPTION,
    MAX_POLICYHOLDER_EVIDENCE,
)
from claim_agent.workflow.denial_coverage_orchestrator import run_denial_coverage_workflow
from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow
from claim_agent.workflow.follow_up_orchestrator import run_follow_up_workflow
from claim_agent.workflow.siu_orchestrator import run_siu_investigation as run_siu_investigation_workflow
from claim_agent.api.routes._claims_helpers import get_claim_context

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class FollowUpRunBody(BaseModel):
    task: str = Field(..., min_length=1, description="Follow-up task (e.g., 'Gather photos from claimant')")
    user_response: Optional[str] = Field(default=None, description="Optional user response when recording in same run")


class RecordFollowUpResponseBody(BaseModel):
    message_id: int = Field(..., description="Follow-up message ID from send_user_message")
    response_content: str = Field(..., min_length=1, description="User's response text")


class DisputeBody(BaseModel):
    dispute_type: str = Field(..., description="Dispute type: liability_determination, valuation_disagreement, repair_estimate, or deductible_application")
    dispute_description: str = Field(
        ...,
        max_length=MAX_DISPUTE_DESCRIPTION,
        description="Policyholder's description of the dispute",
    )
    policyholder_evidence: Optional[str] = Field(default=None, description="Optional supporting evidence references")


class DisputeResponse(BaseModel):
    """Response from filing a policyholder dispute."""

    claim_id: str = Field(..., description="Claim ID")
    dispute_type: str = Field(..., description="Dispute category")
    resolution_type: str = Field(..., description="auto_resolved or escalated")
    status: str = Field(..., description="Final claim status after dispute workflow")
    workflow_output: str = Field(..., description="Raw workflow output from dispute crew")
    adjusted_amount: Optional[float] = Field(default=None, description="Revised payout if auto-resolved and adjusted")
    summary: str = Field(..., description="Short summary of the resolution")


class SupplementalBody(BaseModel):
    """Request body for filing a supplemental damage report."""

    supplemental_damage_description: str = Field(
        ...,
        max_length=2000,
        description="Description of the additional damage discovered during repair",
    )
    reported_by: Optional[Literal["shop", "adjuster", "policyholder"]] = Field(
        default=None,
        description="Who reported: shop, adjuster, or policyholder",
    )


class SupplementalResponse(BaseModel):
    """Response from supplemental workflow."""

    claim_id: str = Field(..., description="Claim ID")
    status: str = Field(..., description="Claim status after supplemental workflow")
    supplemental_amount: Optional[float] = Field(
        default=None,
        description="Supplemental estimate amount",
    )
    combined_insurance_pays: Optional[float] = Field(
        default=None,
        description="Combined original + supplemental insurance payment",
    )
    workflow_output: str = Field(..., description="Raw workflow output")
    summary: str = Field(..., description="Short summary")


class DenialCoverageBody(BaseModel):
    """Request body for denial/coverage dispute workflow."""

    denial_reason: str = Field(
        ...,
        min_length=1,
        max_length=MAX_DENIAL_REASON,
        description="Stated reason for the denial",
    )
    policyholder_evidence: Optional[str] = Field(
        default=None,
        max_length=MAX_POLICYHOLDER_EVIDENCE,
        description="Optional evidence or argument from policyholder",
    )
    state: Optional[str] = Field(
        default="California",
        description="State jurisdiction for compliance (California, Texas, Florida, New York)",
    )


class DenialCoverageResponse(BaseModel):
    """Response from denial/coverage workflow."""

    claim_id: str = Field(..., description="Claim ID")
    outcome: str = Field(
        ...,
        description="outcome: uphold_denial, route_to_appeal, or escalated",
    )
    status: str = Field(..., description="Claim status after workflow")
    workflow_output: str = Field(..., description="Raw workflow output")
    summary: str = Field(..., description="Short summary")


# ---------------------------------------------------------------------------
# Follow-up routes
# ---------------------------------------------------------------------------


@router.post("/claims/{claim_id}/follow-up/run", dependencies=[RequireAdjuster])
def run_follow_up(
    claim_id: str,
    body: FollowUpRunBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Run the follow-up agent to send outreach or process a response."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    try:
        result = run_follow_up_workflow(
            claim_id,
            body.task,
            ctx=ctx,
            user_response=body.user_response,
        )
        return result
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/claims/{claim_id}/follow-up/record-response", dependencies=[RequireAdjuster])
def record_follow_up_response(
    claim_id: str,
    body: RecordFollowUpResponseBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Record a user's response to a follow-up message (webhook or manual entry)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.repo.record_follow_up_response(
            body.message_id,
            body.response_content,
            actor_id=actor_id,
            expected_claim_id=claim_id,
        )
        return {"success": True, "message": "Response recorded"}
    except FollowUpMessageNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DomainValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/claims/{claim_id}/follow-up", dependencies=[RequireAdjuster])
def get_follow_up_messages(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get all follow-up messages for a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    return {"claim_id": claim_id, "messages": ctx.repo.get_follow_up_messages(claim_id)}


# ---------------------------------------------------------------------------
# SIU investigation route
# ---------------------------------------------------------------------------


@router.post("/claims/{claim_id}/siu-investigate", dependencies=[RequireAdjuster])
def run_siu_investigation(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Run SIU investigation crew on a claim under investigation.

    Performs document verification, records investigation, and case management.
    Claim must have status under_investigation or fraud_suspected.
    Creates SIU case if not already present.
    """
    claim = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    status = claim.get("status")
    if status not in SIU_INVESTIGATION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"SIU investigation requires status under_investigation or fraud_suspected; got {status!r}",
        )
    try:
        result = run_siu_investigation_workflow(claim_id, ctx=ctx)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


# ---------------------------------------------------------------------------
# Dispute route
# ---------------------------------------------------------------------------


@router.post("/claims/{claim_id}/dispute", response_model=DisputeResponse, dependencies=[RequireAdjuster])
async def file_dispute(
    claim_id: str,
    body: DisputeBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """File a policyholder dispute on an existing claim.

    Runs the dispute resolution workflow which auto-resolves simple disputes
    (valuation, repair estimate, deductible) and escalates complex ones
    (liability) to human adjusters.
    """
    claim = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    claim_status = claim.get("status")
    if claim_status not in DISPUTABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Claim cannot be disputed in status {claim_status!r}. "
                f"Disputes are allowed only for claims with status: {', '.join(DISPUTABLE_STATUSES)}."
            ),
        )

    try:
        DisputeType(body.dispute_type)
    except ValueError:
        valid = [t.value for t in DisputeType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid dispute_type. Must be one of: {', '.join(valid)}",
        )

    dispute_data = {
        "claim_id": claim_id,
        "dispute_type": body.dispute_type,
        "dispute_description": body.dispute_description,
        "policyholder_evidence": body.policyholder_evidence,
    }

    result = await asyncio.to_thread(
        run_dispute_workflow,
        dispute_data,
        ctx=ctx,
    )
    return result


# ---------------------------------------------------------------------------
# Denial/coverage route
# ---------------------------------------------------------------------------


@router.post(
    "/claims/{claim_id}/denial-coverage",
    response_model=DenialCoverageResponse,
    dependencies=[RequireAdjuster],
)
async def run_denial_coverage(
    claim_id: str,
    body: DenialCoverageBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Run denial/coverage dispute workflow on a denied claim.

    Reviews denial reason, verifies coverage/exclusions, and either generates
    a denial letter (uphold) or routes to appeal.
    """
    claim = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    claim_status = claim.get("status")
    if claim_status not in DENIAL_COVERAGE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Claim cannot run denial/coverage workflow in status {claim_status!r}. "
                f"Allowed statuses: {', '.join(DENIAL_COVERAGE_STATUSES)}."
            ),
        )

    denial_data = {
        "claim_id": claim_id,
        "denial_reason": body.denial_reason,
        "policyholder_evidence": body.policyholder_evidence,
    }
    try:
        state = normalize_state(body.state or "California")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    result = await asyncio.to_thread(
        run_denial_coverage_workflow,
        denial_data,
        ctx=ctx,
        state=state,
    )
    return result


# ---------------------------------------------------------------------------
# Supplemental route
# ---------------------------------------------------------------------------


@router.post(
    "/claims/{claim_id}/supplemental",
    response_model=SupplementalResponse,
    dependencies=[RequireAdjuster],
)
async def file_supplemental(
    claim_id: str,
    body: SupplementalBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """File a supplemental damage report on an existing partial loss claim.

    Runs the supplemental workflow when additional damage is discovered during
    repair. Validates the report, compares to original estimate, calculates
    supplemental amount, and updates the repair authorization.
    """
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    try:
        return await execute_supplemental_request(
            claim_id=claim_id,
            supplemental_damage_description=body.supplemental_damage_description,
            reported_by=body.reported_by,
            ctx=ctx,
        )
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        msg = str(e)
        code = 409 if "cannot receive supplemental" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from e
