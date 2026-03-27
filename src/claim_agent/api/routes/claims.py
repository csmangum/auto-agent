"""Claims API routes: listing, detail, audit log, workflow runs, statistics."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import (
    adjuster_identity_scopes_assignee,
    ensure_claim_access_for_adjuster,
    filter_related_claim_ids_for_adjuster,
)
from claim_agent.api.idempotency import (
    get_idempotency_key_and_cached,
    release_idempotency_on_error,
    store_response_if_idempotent,
)
from claim_agent.api.deps import require_role
from claim_agent.config import get_settings
from claim_agent.exceptions import (
    ClaimAlreadyProcessingError,
    ClaimNotFoundError,
    InvalidClaimTransitionError,
    ReserveAuthorityError,
)
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.constants import VALID_REPAIR_STATUSES

from claim_agent.db.database import get_db_path
from claim_agent.db.incident_repository import IncidentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.db.repair_status_repository import RepairStatusRepository
from claim_agent.models.claim import ClaimRecord
from claim_agent.models.incident import (
    BIAllocationInput,
    ClaimLinkInput,
    IncidentDetailResponse,
    IncidentInput,
    IncidentOutput,
    IncidentRecord,
    RelatedClaimsResponse,
)
from claim_agent.services.bi_allocation import allocate_bi_limits
from claim_agent.tools.partial_loss_logic import _parse_partial_loss_workflow_output
from claim_agent.mock_crew.claim_generator import (
    generate_claim_from_prompt,
    generate_incident_damage_from_vehicle,
)
import claim_agent.api.routes._claims_helpers as _claims_helpers
from claim_agent.api.routes._claims_helpers import (
    GenerateClaimRequest,
    GenerateIncidentDetailsRequest,
    get_claim_context,
    http_already_processing as _http_already_processing,
    process_claim_with_attachments as _process_claim_with_attachments,
    run_workflow_background as _run_workflow_background,
    sanitize_incident_data as _sanitize_incident_data,
    try_run_workflow_background as _try_run_workflow_background,
)

logger = logging.getLogger(__name__)

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


class RepairStatusUpdateBody(BaseModel):
    """Request body for updating repair status (simulation/dashboard)."""

    status: str = Field(..., min_length=1, max_length=64)
    shop_id: str | None = Field(default=None, max_length=128)
    authorization_id: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


@router.post("/claims/{claim_id}/repair-status", dependencies=[RequireAdjuster])
def update_claim_repair_status(
    claim_id: str,
    body: RepairStatusUpdateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
):
    """Update repair status (for simulation/dashboard). Infers shop_id from workflow if omitted."""
    if body.status not in VALID_REPAIR_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {sorted(VALID_REPAIR_STATUSES)}",
        )
    claim_repo = ClaimRepository(db_path=get_db_path())
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


@router.post("/claims/generate")
async def generate_and_submit_claim(
    request: Request,
    body: GenerateClaimRequest = Body(...),
    async_mode: bool = Query(False, alias="async", description="If submit=true, return claim_id immediately and process in background"),
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
            max_tasks = get_settings().max_concurrent_background_tasks
            async with _claims_helpers.background_tasks_lock:
                if max_tasks > 0 and len(_claims_helpers.background_tasks) >= max_tasks:
                    release_idempotency_on_error(idem_key)
                    raise HTTPException(
                        status_code=503,
                        detail="Too many concurrent background tasks. Retry later.",
                        headers={"Retry-After": "60"},
                    )

        actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
        claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
            claim_input, None, actor_id, ctx=ctx,
        )

        if async_mode:
            _run_workflow_background(
                claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
            )
            result = {"claim": claim_data, "submitted": True, "claim_id": claim_id}
        else:
            try:
                result = await asyncio.to_thread(
                    run_claim_workflow,
                    claim_data_with_attachments,
                    None,
                    claim_id,
                    actor_id=actor_id,
                    ctx=ctx,
                )
            except ClaimAlreadyProcessingError as e:
                _http_already_processing(e)
            result = {"claim": claim_data, "submitted": True, **result}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.post("/claims/generate-incident-details")
async def generate_incident_details(
    body: GenerateIncidentDetailsRequest = Body(...),
    auth: AuthContext = RequireAdjuster,
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
    except InvalidClaimTransitionError:
        raise
    except Exception as e:
        logger.exception("generate-incident-details failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Incident details generation is temporarily unavailable. Please try again later.",
        ) from e
    return result


@router.post("/incidents", response_model=IncidentOutput)
async def create_incident(
    request: Request,
    incident_input: IncidentInput = Body(..., description="Multi-vehicle incident data"),
    async_mode: bool = Query(False, alias="async", description="Process each claim in background"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create an incident with multiple vehicle claims (multi-vehicle accident).

    One incident can involve multiple vehicles; each vehicle becomes a separate claim
    linked to the incident. Claims are automatically linked as same_incident.
    """
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW

    try:
        # Sanitize incident data before processing
        incident_dict = incident_input.model_dump(mode="python")
        sanitized_incident = _sanitize_incident_data(incident_dict)
        try:
            sanitized_input = IncidentInput.model_validate(sanitized_incident)
        except ValidationError as e:
            raise HTTPException(status_code=400, detail=f"Invalid incident data: {e}") from e

        incident_repo = IncidentRepository(db_path=get_db_path())
        incident_id, claim_ids = incident_repo.create_incident(sanitized_input, actor_id=actor_id)

        if async_mode and claim_ids:
            scheduling_status: dict[str, str] = {}
            for claim_id in claim_ids:
                claim = ctx.repo.get_claim(claim_id)
                if claim:
                    claim_data = claim_data_from_row(claim)
                    task = await _try_run_workflow_background(
                        claim_id, claim_data, actor_id, ctx=ctx,
                    )
                    scheduling_status[claim_id] = "scheduled" if task is not None else "capacity_exceeded"
                else:
                    logger.error(
                        "Claim %s created by incident %s not found when scheduling background workflow; "
                        "possible data integrity issue",
                        claim_id,
                        incident_id,
                    )
                    scheduling_status[claim_id] = "claim_not_found"

            result = IncidentOutput(
                incident_id=incident_id,
                claim_ids=claim_ids,
                message=f"Incident {incident_id} created with {len(claim_ids)} claim(s)",
                background_scheduling=scheduling_status,
            )
        else:
            result = IncidentOutput(
                incident_id=incident_id,
                claim_ids=claim_ids,
                message=f"Incident {incident_id} created with {len(claim_ids)} claim(s)",
            )
        store_response_if_idempotent(idem_key, 200, result.model_dump(mode="json"))
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.get("/incidents/{incident_id}", response_model=IncidentDetailResponse)
async def get_incident(
    incident_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get incident details and linked claims."""
    incident_repo = IncidentRepository(db_path=get_db_path())
    incident = incident_repo.get_incident(incident_id)
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    claims = incident_repo.get_claims_by_incident(incident_id)
    if adjuster_identity_scopes_assignee(auth):
        claims = [c for c in claims if (c.get("assignee") or "") == auth.identity]
        if not claims:
            raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentDetailResponse(
        incident=IncidentRecord.model_validate(incident),
        claims=[ClaimRecord.model_validate(c) for c in claims],
    )


@router.post("/claim-links")
async def create_claim_link(
    request: Request,
    link_input: ClaimLinkInput = Body(..., description="Link between two claims"),
    auth: AuthContext = RequireAdjuster,
):
    """Link two claims for cross-carrier or same-incident coordination.

    Use for: opposing_carrier (your insured hit their insured), subrogation,
    cross_carrier, or same_incident when linking claims from different submissions.
    """
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    try:
        claim_repo = ClaimRepository(db_path=get_db_path())
        for cid in (link_input.claim_id_a, link_input.claim_id_b):
            ensure_claim_access_for_adjuster(auth, cid, claim_repo.get_claim(cid))
        incident_repo = IncidentRepository(db_path=get_db_path())
        link_id = incident_repo.create_claim_link(
            link_input.claim_id_a,
            link_input.claim_id_b,
            link_input.link_type,
            opposing_carrier=link_input.opposing_carrier,
            notes=link_input.notes,
        )
        if link_id is None:
            raise HTTPException(
                status_code=409,
                detail="A claim link with this combination already exists",
            )
        result = {"link_id": link_id, "message": "Claim link created"}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.get("/claims/{claim_id}/related", response_model=RelatedClaimsResponse)
async def get_related_claims(
    claim_id: str,
    link_type: Optional[str] = Query(None, description="Filter by link type"),
    auth: AuthContext = RequireAdjuster,
):
    """Get claims related to this claim (same incident, opposing carrier, etc.)."""
    claim_repo = ClaimRepository(db_path=get_db_path())
    ensure_claim_access_for_adjuster(auth, claim_id, claim_repo.get_claim(claim_id))
    incident_repo = IncidentRepository(db_path=get_db_path())
    related = incident_repo.get_related_claims(claim_id, link_type=link_type)
    if adjuster_identity_scopes_assignee(auth):
        related = filter_related_claim_ids_for_adjuster(auth, claim_repo, related)
    return RelatedClaimsResponse(claim_id=claim_id, related_claim_ids=related)


@router.post("/bi-allocation")
async def allocate_bi(
    allocation_input: BIAllocationInput = Body(..., description="BI limit allocation request"),
    auth: AuthContext = RequireAdjuster,
):
    """Allocate BI per-accident limit across multiple claimants when demands exceed limit.

    Use when multiple BI claimants exceed the policy's per_accident limit.
    Methods: proportional (default), severity_weighted, equal.
    """
    claim_repo = ClaimRepository(db_path=get_db_path())
    ensure_claim_access_for_adjuster(
        auth, allocation_input.claim_id, claim_repo.get_claim(allocation_input.claim_id)
    )
    result = allocate_bi_limits(allocation_input)
    return result.model_dump()
