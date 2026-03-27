"""Core CRUD routes for claims: list, detail, status, stats, review queue, and create."""

import asyncio
import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import text

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import (
    adjuster_identity_scopes_assignee,
    ensure_claim_access_for_adjuster,
)
from claim_agent.api.deps import require_role
from claim_agent.api.idempotency import (
    get_idempotency_key_and_cached,
    release_idempotency_on_error,
    store_response_if_idempotent,
)
from claim_agent.config import get_settings
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.constants import STATUS_ARCHIVED, STATUS_PURGED
from claim_agent.db.database import get_connection, row_to_dict
from claim_agent.exceptions import ClaimAlreadyProcessingError
from claim_agent.models.claim import ClaimInput
from claim_agent.workflow.helpers import WORKFLOW_STAGES
import claim_agent.api.routes._claims_helpers as _claims_helpers
from claim_agent.api.routes._claims_helpers import (
    ALLOWED_SORT_FIELDS as _ALLOWED_SORT_FIELDS,
    PRIORITY_VALUES,
    adjuster_scope_params as _adjuster_scope_params,
    apply_adjuster_claim_filter as _apply_adjuster_claim_filter,
    get_claim_context,
    http_already_processing as _http_already_processing,
    process_claim_with_attachments as _process_claim_with_attachments,
    resolve_attachment_urls as _resolve_attachment_urls,
    run_workflow_background as _run_workflow_background,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")


@router.get("/claims/stats")
def get_claims_stats(auth: AuthContext = RequireAdjuster):
    """Aggregate statistics: count by status, count by type, totals."""
    scope = _adjuster_scope_params(auth)
    adj = adjuster_identity_scopes_assignee(auth)
    cwhere = " WHERE assignee = :_scope_assignee" if adj else ""
    sub_claims = (
        "SELECT id FROM claims WHERE assignee = :_scope_assignee" if adj else "SELECT id FROM claims"
    )
    with get_connection() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) as cnt FROM claims{cwhere}"),
            scope,
        ).fetchone()[0]
        status_rows = conn.execute(
            text(
                f"SELECT COALESCE(status, 'unknown') as status, COUNT(*) as cnt FROM claims{cwhere} "
                "GROUP BY status ORDER BY cnt DESC"
            ),
            scope,
        ).fetchall()
        by_status = {row_to_dict(r)["status"]: row_to_dict(r)["cnt"] for r in status_rows}
        type_rows = conn.execute(
            text(
                f"SELECT COALESCE(claim_type, 'unclassified') as claim_type, COUNT(*) as cnt FROM claims{cwhere} "
                "GROUP BY claim_type ORDER BY cnt DESC"
            ),
            scope,
        ).fetchall()
        by_type = {row_to_dict(r)["claim_type"]: row_to_dict(r)["cnt"] for r in type_rows}
        date_row = conn.execute(
            text(f"SELECT MIN(created_at) as earliest, MAX(created_at) as latest FROM claims{cwhere}"),
            scope,
        ).fetchone()
        date_d = row_to_dict(date_row) if date_row else {}
        if adj:
            audit_count = conn.execute(
                text(
                    f"SELECT COUNT(*) as cnt FROM claim_audit_log WHERE claim_id IN ({sub_claims})"
                ),
                scope,
            ).fetchone()[0]
            workflow_count = conn.execute(
                text(
                    f"SELECT COUNT(*) as cnt FROM workflow_runs WHERE claim_id IN ({sub_claims})"
                ),
                scope,
            ).fetchone()[0]
        else:
            audit_count = conn.execute(text("SELECT COUNT(*) as cnt FROM claim_audit_log")).fetchone()[0]
            workflow_count = conn.execute(text("SELECT COUNT(*) as cnt FROM workflow_runs")).fetchone()[0]

    return {
        "total_claims": total,
        "by_status": by_status,
        "by_type": by_type,
        "earliest_claim": date_d.get("earliest"),
        "latest_claim": date_d.get("latest"),
        "total_audit_events": audit_count,
        "total_workflow_runs": workflow_count,
    }


@router.get("/claims", dependencies=[RequireAdjuster])
def list_claims(
    status: Optional[str] = Query(None, description="Filter by status"),
    claim_type: Optional[str] = Query(None, description="Filter by claim type"),
    include_archived: bool = Query(False, description="Include archived claims (retention)"),
    include_purged: bool = Query(False, description="Include purged claims (retention)"),
    search: Optional[str] = Query(
        None, description="Free-text search across claim id, policy_number, and vin", max_length=200
    ),
    sort_by: str = Query("created_at", description="Field to sort by"),
    sort_order: str = Query("desc", description="Sort direction: asc or desc"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List claims with optional filtering, search, and sorting. Archived and purged claims are excluded by default.

    Search uses SQL LIKE with wildcards on id, policy_number, and vin; large tables may need FTS
    or prefix-style matching for performance.
    """
    if sort_by not in _ALLOWED_SORT_FIELDS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid sort_by '{sort_by}'. Must be one of: {sorted(_ALLOWED_SORT_FIELDS)}",
        )
    if sort_order not in ("asc", "desc"):
        raise HTTPException(
            status_code=400,
            detail="Invalid sort_order. Must be 'asc' or 'desc'.",
        )

    conditions = []
    params: dict[str, Any] = {}

    if status:
        conditions.append("status = :status")
        params["status"] = status
    if not include_archived and (status is None or status != STATUS_ARCHIVED):
        conditions.append("status != :archived")
        params["archived"] = STATUS_ARCHIVED
    if not include_purged and (status is None or status != STATUS_PURGED):
        conditions.append("status != :purged")
        params["purged"] = STATUS_PURGED
    if claim_type:
        conditions.append("claim_type = :claim_type")
        params["claim_type"] = claim_type
    if search:
        conditions.append(
            "(LOWER(id) LIKE LOWER(:search) OR LOWER(policy_number) LIKE LOWER(:search) OR LOWER(vin) LIKE LOWER(:search))"
        )
        params["search"] = f"%{search}%"

    _apply_adjuster_claim_filter(auth, conditions, params)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    params["limit"] = limit
    params["offset"] = offset
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}

    # sort_by and sort_order are validated against the allowlist above; safe to interpolate
    order_clause = f"{sort_by} {sort_order.upper()}"

    with get_connection() as conn:
        count_row = conn.execute(
            text(f"SELECT COUNT(*) as cnt FROM claims {where}"),
            count_params,
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            text(f"SELECT * FROM claims {where} ORDER BY {order_clause} LIMIT :limit OFFSET :offset"),
            params,
        ).fetchall()

    return {
        "claims": [
            _resolve_attachment_urls(row_to_dict(r))
            for r in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/claims/review-queue", dependencies=[RequireAdjuster])
def get_review_queue(
    assignee: Optional[str] = Query(None, description="Filter by assignee"),
    priority: Optional[str] = Query(None, description="Filter by priority"),
    older_than_hours: Optional[float] = Query(None, ge=0, description="Claims older than N hours in queue"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List claims with status needs_review for the adjuster workflow."""
    if priority is not None and priority not in PRIORITY_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority: {priority}. Must be one of: {', '.join(PRIORITY_VALUES)}",
        )
    eff_assignee: str | None
    if adjuster_identity_scopes_assignee(auth):
        eff_assignee = auth.identity
    else:
        eff_assignee = assignee
    claims, total = ctx.repo.list_claims_needing_review(
        assignee=eff_assignee,
        priority=priority,
        older_than_hours=older_than_hours,
        limit=limit,
        offset=offset,
    )
    return {
        "claims": [
            _resolve_attachment_urls(c)
            for c in claims
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/claims/{claim_id}/status", dependencies=[RequireAdjuster])
def get_claim_status(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Lightweight status polling endpoint for async claim processing.

    Returns claim_id, status, claim_type, progress (completed workflow stages),
    and workflow_run_id. Use for efficient polling when POST returned claim_id
    immediately. For real-time updates, use GET /claims/{claim_id}/stream (SSE).
    """
    claim_dict = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    status = claim_dict.get("status") or ""
    claim_type = claim_dict.get("claim_type") or ""

    completed_stages: list[str] = []
    with get_connection() as conn:
        cp_rows = conn.execute(
            text("""
            SELECT stage_key FROM task_checkpoints
            WHERE claim_id = :claim_id AND workflow_run_id = (
                SELECT workflow_run_id FROM task_checkpoints
                WHERE claim_id = :claim_id ORDER BY id DESC LIMIT 1
            )
            """),
            {"claim_id": claim_id},
        ).fetchall()
        for r in cp_rows:
            d = row_to_dict(r)
            sk = d.get("stage_key", "")
            stage = sk.split(":")[0] if ":" in sk else sk
            if stage in WORKFLOW_STAGES:
                completed_stages.append(sk)
        completed_stages.sort(
            key=lambda s: (
                WORKFLOW_STAGES.index(stg)
                if (stg := (s.split(":")[0] if ":" in s else s)) in WORKFLOW_STAGES
                else len(WORKFLOW_STAGES)
            )
        )

    latest_run_id = ctx.repo.get_latest_checkpointed_run_id(claim_id)

    return {
        "claim_id": claim_id,
        "status": status,
        "claim_type": claim_type,
        "progress": completed_stages,
        "workflow_run_id": latest_run_id,
        "created_at": claim_dict.get("created_at"),
    }


@router.get("/claims/{claim_id}", dependencies=[RequireAdjuster])
def get_claim(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get a single claim by ID. Includes claim notes and follow-up messages."""
    row = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    result = _resolve_attachment_urls(
        row,
        repo=ctx.repo,
        actor_id=actor_id,
        audit_presigned=True,
    )
    result["notes"] = ctx.repo.get_notes(claim_id)
    result["follow_up_messages"] = ctx.repo.get_follow_up_messages(claim_id)
    result["parties"] = ctx.repo.get_claim_parties(claim_id)
    tasks, tasks_total = ctx.repo.get_tasks_for_claim(claim_id)
    result["tasks"] = tasks
    result["tasks_total"] = tasks_total
    result["subrogation_cases"] = ctx.repo.get_subrogation_cases_by_claim(claim_id)
    return result


@router.post("/claims")
async def create_claim(
    request: Request,
    claim_input: ClaimInput = Body(..., description="Claim data as JSON"),
    async_mode: bool = Query(False, alias="async", description="If true, return claim_id immediately and process in background"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Submit a new claim for processing. Accepts ClaimInput JSON body.

    Use for programmatic access: portals, batch ingestion, third-party integrations.
    For file uploads, use POST /api/claims/process with multipart form.
    """
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
            result = {"claim_id": claim_id}
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
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise
