"""Workflow processing routes for claims: submit, async submit, SSE stream, and reprocess."""

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

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
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.exceptions import ClaimAlreadyProcessingError
from claim_agent.models.claim import ClaimInput
from claim_agent.workflow.helpers import WORKFLOW_STAGES
import claim_agent.api.routes._claims_helpers as _claims_helpers
from claim_agent.api.routes._claims_helpers import (
    BACKGROUND_QUEUE_FULL_RETRY_AFTER,
    get_claim_context,
    http_already_processing as _http_already_processing,
    process_claim_with_attachments as _process_claim_with_attachments,
    stream_claim_updates as _stream_claim_updates,
    try_run_workflow_background as _try_run_workflow_background,
)

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")
RequireSupervisor = require_role("supervisor", "admin", "executive")


@router.post("/claims/process")
async def process_claim(
    request: Request,
    claim: str = Form(..., description="Claim data as JSON string"),
    files: Optional[list[UploadFile]] = File(default=None, description="Optional attachment files"),
    async_mode: bool = Query(False, alias="async", description="If true, return claim_id immediately and process in background"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Submit a new claim for processing. Accepts claim JSON and optional file uploads.

    - claim: JSON string with policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
      incident_date, incident_description, damage_description, estimated_damage (optional),
      attachments (optional list of {url, type, description}).
    - files: Optional multipart files (photos, PDFs, estimates). Stored via configured backend.
    - async: If true, returns claim_id immediately; workflow runs in background. Use
      GET /claims/{claim_id}/status to poll or GET /claims/{claim_id}/stream for SSE updates.
    """
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
            claim, files, actor_id, ctx=ctx,
        )

        if async_mode:
            task = await _try_run_workflow_background(
                claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
            )
            if task is None:
                release_idempotency_on_error(idem_key)
                raise HTTPException(
                    status_code=503,
                    detail="Too many concurrent background tasks. Retry later.",
                    headers={"Retry-After": BACKGROUND_QUEUE_FULL_RETRY_AFTER},
                )
            result = {"claim_id": claim_id}
        else:
            try:
                result = await asyncio.to_thread(
                    run_claim_workflow,
                    claim_data_with_attachments,
                    None,  # llm
                    claim_id,  # existing_claim_id
                    actor_id=actor_id,
                    ctx=ctx,
                )
            except ClaimAlreadyProcessingError as e:
                _http_already_processing(e)
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.post("/claims/process/async")
async def process_claim_async(
    request: Request,
    claim: str = Form(..., description="Claim data as JSON string"),
    files: Optional[list[UploadFile]] = File(default=None, description="Optional attachment files"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Submit a new claim for async processing. Returns claim_id immediately; workflow runs in background.
    Use GET /claims/{claim_id}/stream to receive realtime updates."""
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    try:
        if await _claims_helpers.background_workflow_queue_full():
            release_idempotency_on_error(idem_key)
            raise HTTPException(
                status_code=503,
                detail="Too many concurrent background tasks. Retry later.",
                headers={"Retry-After": BACKGROUND_QUEUE_FULL_RETRY_AFTER},
            )

        actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
        claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
            claim, files, actor_id, ctx=ctx,
        )
        task = await _try_run_workflow_background(
            claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
        )
        if task is None:
            release_idempotency_on_error(idem_key)
            raise HTTPException(
                status_code=503,
                detail="Too many concurrent background tasks. Retry later.",
                headers={"Retry-After": BACKGROUND_QUEUE_FULL_RETRY_AFTER},
            )
        result = {"claim_id": claim_id}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.get("/claims/{claim_id}/stream")
async def stream_claim_updates(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Server-Sent Events stream of claim status, audit log, and workflow runs.
    Polls every second until claim status is no longer pending/processing."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    return StreamingResponse(
        _stream_claim_updates(claim_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/claims/{claim_id}/reprocess")
async def reprocess_claim(
    claim_id: str,
    from_stage: Optional[str] = Query(
        None,
        description=(
            "Resume from this stage using checkpoints from the most recent workflow run. "
            f"Must be one of: {', '.join(WORKFLOW_STAGES)}"
        ),
    ),
    auth: AuthContext = RequireSupervisor,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Re-run workflow for an existing claim. Requires supervisor role.

    Pass ``from_stage`` to resume from a specific stage using checkpoints from
    the most recent workflow run.
    """
    if from_stage is not None and from_stage not in WORKFLOW_STAGES:
        raise HTTPException(
            status_code=400,
            detail=f"from_stage must be one of {', '.join(WORKFLOW_STAGES)}",
        )

    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    claim_data = claim_data_from_row(claim)
    try:
        ClaimInput.model_validate(claim_data)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim data for reprocess: {e}") from e

    resume_run_id: str | None = None
    if from_stage is not None:
        resume_run_id = ctx.repo.get_latest_checkpointed_run_id(claim_id)
        if resume_run_id is None:
            from_stage = None

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        result = await asyncio.to_thread(
            run_claim_workflow,
            claim_data,
            existing_claim_id=claim_id,
            actor_id=actor_id,
            resume_run_id=resume_run_id,
            from_stage=from_stage,
            ctx=ctx,
        )
    except ClaimAlreadyProcessingError as e:
        _http_already_processing(e)
    return result
