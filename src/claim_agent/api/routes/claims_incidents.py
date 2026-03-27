"""Incident management and BI allocation routes for claims."""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import ValidationError

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
from claim_agent.api.deps import RequireAdjuster
from claim_agent.context import ClaimContext
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.database import get_db_path
from claim_agent.db.incident_repository import IncidentRepository
from claim_agent.db.repository import ClaimRepository
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
from claim_agent.api.routes._claims_helpers import (
    get_claim_context,
    sanitize_incident_data as _sanitize_incident_data,
    try_run_workflow_background as _try_run_workflow_background,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])


@router.post("/incidents", response_model=IncidentOutput, dependencies=[RequireAdjuster])
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


@router.get(
    "/incidents/{incident_id}",
    response_model=IncidentDetailResponse,
    dependencies=[RequireAdjuster],
)
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


@router.post("/claim-links", dependencies=[RequireAdjuster])
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


@router.get(
    "/claims/{claim_id}/related",
    response_model=RelatedClaimsResponse,
    dependencies=[RequireAdjuster],
)
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


@router.post("/bi-allocation", dependencies=[RequireAdjuster])
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
