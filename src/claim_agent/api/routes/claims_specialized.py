"""Specialized workflow routes for claims: follow-up, SIU, disputes, denials, supplemental, and mock crew generation."""

import asyncio
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import ensure_claim_access_for_adjuster
from claim_agent.api.deps import require_role
from claim_agent.api.idempotency import (
    get_idempotency_key_and_cached,
    release_idempotency_on_error,
    store_response_if_idempotent,
)
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.constants import (
    DENIAL_COVERAGE_STATUSES,
    DISPUTABLE_STATUSES,
    SIU_INVESTIGATION_STATUSES,
)
from claim_agent.exceptions import ClaimAlreadyProcessingError, ClaimNotFoundError, DomainValidationError
from claim_agent.models.dispute import DisputeType
from claim_agent.mock_crew.claim_generator import (
    generate_claim_from_prompt,
    generate_incident_damage_from_vehicle,
)
from claim_agent.rag.constants import normalize_state
from claim_agent.services.supplemental_request import execute_supplemental_request
from claim_agent.utils.sanitization import (
    MAX_DENIAL_REASON,
    MAX_POLICYHOLDER_EVIDENCE,
)
from claim_agent.workflow.denial_coverage_orchestrator import run_denial_coverage_workflow
from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow
from claim_agent.workflow.follow_up_orchestrator import run_follow_up_workflow
from claim_agent.workflow.siu_orchestrator import run_siu_investigation as run_siu_investigation_workflow
import claim_agent.api.routes._claims_helpers as _claims_helpers
from claim_agent.api.routes._claims_helpers import (
    BACKGROUND_QUEUE_FULL_RETRY_AFTER,
    GenerateClaimRequest,
    GenerateIncidentDetailsRequest,
    get_claim_context,
    http_already_processing as _http_already_processing,
    process_claim_with_attachments as _process_claim_with_attachments,
    try_run_workflow_background as _try_run_workflow_background,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")


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
    dispute_description: str = Field(..., description="Policyholder's description of the dispute")
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
    except DomainValidationError as e:
        msg = str(e)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e
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


@router.post("/claims/{claim_id}/siu-investigate")
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


@router.post("/claims/{claim_id}/dispute", response_model=DisputeResponse)
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


@router.post("/claims/{claim_id}/denial-coverage", response_model=DenialCoverageResponse)
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


@router.post("/claims/{claim_id}/supplemental", response_model=SupplementalResponse)
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


# ---------------------------------------------------------------------------
# Mock Crew claim generation routes (requires MOCK_CREW_ENABLED)
# ---------------------------------------------------------------------------


@router.post("/claims/generate")
async def generate_and_submit_claim(
    request: Request,
    body: GenerateClaimRequest = Body(...),
    async_mode: bool = Query(
        False,
        alias="async",
        description="If submit=true, return claim_id immediately and process in background",
    ),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Generate claim data via Mock Crew LLM from a prompt, then optionally submit.

    Requires MOCK_CREW_ENABLED=true. The LLM produces realistic ClaimInput JSON
    from the prompt (e.g. "partial loss, Honda Accord, parking lot fender bender").
    If submit=true, the claim is created and the workflow runs. If submit=false,
    returns the generated claim JSON without creating or processing it (useful for
    inspection). When async=true and submit=true, returns claim_id immediately;
    use GET /claims/{claim_id}/status or /stream to poll for completion.
    """
    try:
        claim_input = await asyncio.to_thread(
            generate_claim_from_prompt,
            body.prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    claim_data = claim_input.model_dump(mode="json")
    if not body.submit:
        return {"claim": claim_data, "submitted": False}

    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    try:
        if async_mode:
            if await _claims_helpers.background_workflow_queue_full():
                release_idempotency_on_error(idem_key)
                raise HTTPException(
                    status_code=503,
                    detail="Too many concurrent background tasks. Retry later.",
                    headers={"Retry-After": BACKGROUND_QUEUE_FULL_RETRY_AFTER},
                )

        actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
        claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
            claim_input,
            None,
            actor_id,
            ctx=ctx,
        )

        if async_mode:
            task = await _try_run_workflow_background(
                claim_id,
                claim_data_with_attachments,
                actor_id,
                ctx=ctx,
            )
            if task is None:
                release_idempotency_on_error(idem_key)
                raise HTTPException(
                    status_code=503,
                    detail="Too many concurrent background tasks. Retry later.",
                    headers={"Retry-After": BACKGROUND_QUEUE_FULL_RETRY_AFTER},
                )
            result = {"claim": claim_data, "submitted": True, "claim_id": claim_id}
        else:
            try:
                wf_result = await asyncio.to_thread(
                    run_claim_workflow,
                    claim_data_with_attachments,
                    None,
                    claim_id,
                    actor_id=actor_id,
                    ctx=ctx,
                )
            except ClaimAlreadyProcessingError as e:
                _http_already_processing(e)
            result = {"claim": claim_data, "submitted": True, **wf_result}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.post("/claims/generate-incident-details")
async def generate_incident_details(
    body: GenerateIncidentDetailsRequest = Body(...),
    _auth: AuthContext = RequireAdjuster,
):
    """Generate incident/damage details via Mock Crew LLM for a given vehicle.

    Requires MOCK_CREW_ENABLED=true. Returns incident_date, incident_description,
    damage_description, and estimated_damage for use in the New Claim form.
    """
    try:
        result = await asyncio.to_thread(
            generate_incident_damage_from_vehicle,
            body.vehicle_year,
            body.vehicle_make,
            body.vehicle_model,
            body.prompt,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("generate-incident-details failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Incident details generation is temporarily unavailable. Please try again later.",
        ) from e
    return result
