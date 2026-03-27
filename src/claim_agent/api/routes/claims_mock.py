"""Mock Crew claim generation routes (requires MOCK_CREW_ENABLED)."""

import asyncio
import logging

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import RequireAdjuster
from claim_agent.api.http_constants import BACKGROUND_QUEUE_FULL_RETRY_AFTER
from claim_agent.api.idempotency import (
    get_idempotency_key_and_cached,
    release_idempotency_on_error,
    store_response_if_idempotent,
)
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.exceptions import ClaimAlreadyProcessingError, InvalidClaimTransitionError
from claim_agent.api.routes._claims_helpers import (
    GenerateClaimRequest,
    GenerateIncidentDetailsRequest,
    background_queue_full_json_body as _background_queue_full_json_body,
    get_claim_context,
    http_already_processing as _http_already_processing,
    process_claim_with_attachments as _process_claim_with_attachments,
    try_run_workflow_background as _try_run_workflow_background,
)
from claim_agent.mock_crew.claim_generator import (
    generate_claim_from_prompt,
    generate_incident_damage_from_vehicle,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])


@router.post("/claims/generate", dependencies=[RequireAdjuster])
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
                result = _background_queue_full_json_body(
                    claim_id, claim=claim_data, submitted=True
                )
                store_response_if_idempotent(idem_key, 503, result)
                return JSONResponse(
                    status_code=503,
                    content=result,
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


@router.post("/claims/generate-incident-details", dependencies=[RequireAdjuster])
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
    except InvalidClaimTransitionError:
        # Re-raise directly so the global error handler renders the proper response.
        raise
    except Exception as e:
        logger.exception("generate-incident-details failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="Incident details generation is temporarily unavailable. Please try again later.",
        ) from e
    return result
