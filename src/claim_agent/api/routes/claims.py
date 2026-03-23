"""Claims API routes: listing, detail, audit log, workflow runs, statistics."""

import asyncio
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError, field_validator

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
    ClaimNotFoundError,
    DomainValidationError,
    InvalidClaimTransitionError,
    ReserveAuthorityError,
)
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.workflow.handback_orchestrator import run_handback_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.constants import (
    DENIAL_COVERAGE_STATUSES,
    DISPUTABLE_STATUSES,
    SIU_INVESTIGATION_STATUSES,
    STATUS_ARCHIVED,
    STATUS_FAILED,
    STATUS_PURGED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PROCESSING,
    VALID_REPAIR_STATUSES,
)
from sqlalchemy import text

from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.db.incident_repository import IncidentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.db.repair_status_repository import RepairStatusRepository
from claim_agent.db.document_repository import DocumentRepository, build_document_version_groups
from claim_agent.workflow.helpers import WORKFLOW_STAGES
from claim_agent.models.claim import Attachment, ClaimInput, ClaimRecord
from claim_agent.models.party import PartyRelationshipType
from claim_agent.models.incident import (
    BIAllocationInput,
    ClaimLinkInput,
    IncidentDetailResponse,
    IncidentInput,
    IncidentOutput,
    IncidentRecord,
    RelatedClaimsResponse,
)
from claim_agent.models.document import DocumentRequestStatus, DocumentType, ReviewStatus
from claim_agent.models.dispute import DisputeType
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.services.bi_allocation import allocate_bi_limits
from claim_agent.services.portal_verification import create_claim_access_token
from claim_agent.services.repair_shop_portal_tokens import create_repair_shop_access_token
from claim_agent.services.supplemental_request import execute_supplemental_request
from claim_agent.utils import attachment_type_to_document_type, infer_attachment_type
from claim_agent.rag.constants import normalize_state
from claim_agent.tools.partial_loss_logic import _parse_partial_loss_workflow_output
from claim_agent.utils.sanitization import (
    MAX_ACTOR_ID,
    MAX_DENIAL_REASON,
    MAX_PAYOUT,
    MAX_POLICYHOLDER_EVIDENCE,
    _is_safe_attachment_url,
    sanitize_claim_data,
)
from claim_agent.workflow.denial_coverage_orchestrator import run_denial_coverage_workflow
from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow
from claim_agent.workflow.follow_up_orchestrator import run_follow_up_workflow
from claim_agent.workflow.siu_orchestrator import run_siu_investigation as run_siu_investigation_workflow
from claim_agent.mock_crew.claim_generator import (
    generate_claim_from_prompt,
    generate_incident_damage_from_vehicle,
)

logger = logging.getLogger(__name__)


class GenerateClaimRequest(BaseModel):
    """Request body for Mock Crew claim generation."""

    prompt: str = Field(
        ...,
        max_length=2000,
        description="Natural-language description of the claim to generate",
    )
    submit: bool = Field(
        default=True,
        description="If true, submit the generated claim for processing via the workflow",
    )


class GenerateIncidentDetailsRequest(BaseModel):
    """Request body for generating incident/damage details from vehicle info."""

    vehicle_year: int = Field(..., ge=1900, le=2100, description="Vehicle year")
    vehicle_make: str = Field(..., min_length=1, max_length=100, description="Vehicle make")
    vehicle_model: str = Field(..., min_length=1, max_length=100, description="Vehicle model")
    prompt: str = Field(
        default="",
        max_length=2000,
        description="Optional scenario (e.g. parking lot fender bender)",
    )


def get_claim_context() -> ClaimContext:
    """FastAPI dependency providing a per-request ClaimContext."""
    return ClaimContext.from_defaults(db_path=get_db_path())

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin", "executive")
RequireSupervisor = require_role("supervisor", "admin", "executive")

_MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB


def _adjuster_scope_params(auth: AuthContext) -> dict[str, Any]:
    """Query params for adjuster-only claim scoping (assignee matches JWT sub / API key identity)."""
    if not adjuster_identity_scopes_assignee(auth):
        return {}
    return {"_scope_assignee": auth.identity}


def _apply_adjuster_claim_filter(
    auth: AuthContext, conditions: list[str], params: dict[str, Any]
) -> None:
    if adjuster_identity_scopes_assignee(auth):
        conditions.append("assignee = :_scope_assignee")
        params["_scope_assignee"] = auth.identity


# Allowed document upload extensions (security: prevent executable/malicious uploads)
_ALLOWED_DOCUMENT_EXTENSIONS = frozenset(
    {"pdf", "jpg", "jpeg", "png", "gif", "webp", "heic", "doc", "docx", "xls", "xlsx"}
)

# Valid document types for validation
_VALID_DOCUMENT_TYPES = frozenset(dt.value for dt in DocumentType)

_STREAM_POLL_INTERVAL = 1.0  # seconds between DB polls
_STREAM_MAX_DURATION = 300  # 5 min timeout

PRIORITY_VALUES = ("critical", "high", "medium", "low")

_background_tasks: set[asyncio.Task] = set()
_background_tasks_lock = asyncio.Lock()

# Per-claim locks to prevent concurrent approve requests from racing (same claim_id).
# Note: In multi-process deployments, use a distributed lock (e.g. Redis) instead.
# LRU eviction prevents unbounded memory growth in long-running processes.
_approve_locks: dict[str, asyncio.Lock] = {}
_approve_locks_lock = asyncio.Lock()
_MAX_APPROVE_LOCKS = 10000


async def _get_approve_lock(claim_id: str) -> asyncio.Lock:
    """Get or create a lock for the given claim_id."""
    async with _approve_locks_lock:
        if claim_id not in _approve_locks:
            if len(_approve_locks) >= _MAX_APPROVE_LOCKS:
                # Evict oldest entry (FIFO eviction for simplicity)
                _approve_locks.pop(next(iter(_approve_locks)))
            _approve_locks[claim_id] = asyncio.Lock()
        return _approve_locks[claim_id]


def _run_workflow_background(
    claim_id: str,
    claim_data_with_attachments: dict,
    actor_id: str,
    ctx: ClaimContext | None = None,
) -> asyncio.Task:
    """Run claim workflow in background. Returns task for tracking."""
    bg_ctx = ctx or ClaimContext.from_defaults(db_path=get_db_path())

    async def run_in_thread():
        try:
            await asyncio.to_thread(
                run_claim_workflow,
                claim_data_with_attachments,
                None,
                claim_id,
                actor_id=actor_id,
                ctx=bg_ctx,
            )
        except InvalidClaimTransitionError as exc:
            logger.warning(
                "Invalid claim transition in background workflow for claim_id %s",
                claim_id,
                exc_info=True,
            )
            try:
                bg_ctx.repo.update_claim_status(
                    claim_id,
                    STATUS_NEEDS_REVIEW,
                    details=(
                        f"Invalid claim transition in background workflow: "
                        f"{exc.from_status!r} -> {exc.to_status!r} — {exc.reason}"
                    ),
                    actor_id=ACTOR_WORKFLOW,
                    skip_validation=True,
                )
            except Exception:
                logger.exception(
                    "Failed to mark claim %s as needs_review after invalid transition",
                    claim_id,
                )
        except Exception:
            logger.exception(
                "Unhandled exception in background workflow for claim_id %s", claim_id
            )
            try:
                bg_ctx.repo.update_claim_status(
                    claim_id,
                    STATUS_FAILED,
                    details="Background workflow failed",
                    actor_id=ACTOR_WORKFLOW,
                    skip_validation=True,
                )
            except Exception:
                logger.exception(
                    "Failed to mark claim %s as failed after workflow error", claim_id
                )

    task = asyncio.create_task(run_in_thread())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _try_run_workflow_background(
    claim_id: str,
    claim_data_with_attachments: dict,
    actor_id: str,
    ctx: ClaimContext | None = None,
) -> asyncio.Task | None:
    """Run claim workflow in background if under concurrent limit. Returns None when at capacity."""
    max_tasks = get_settings().max_concurrent_background_tasks
    async with _background_tasks_lock:
        if max_tasks > 0 and len(_background_tasks) >= max_tasks:
            return None
        return _run_workflow_background(
            claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
        )


def _resolve_attachment_urls(
    claim_dict: dict,
    *,
    repo: ClaimRepository | None = None,
    actor_id: str | None = None,
    audit_presigned: bool = False,
) -> dict:
    """Convert storage keys to fetchable URLs: presigned for S3, download endpoint for local.

    When ``audit_presigned`` is true and storage is S3, appends ``document_accessed`` audit rows
    for each issued presigned URL (chain of custody). List/review-queue and SSE callers should
    leave ``audit_presigned`` false to avoid log flooding and per-row DB writes.
    """
    if "attachments" not in claim_dict or not claim_dict["attachments"]:
        return claim_dict

    do_audit = False
    try:
        raw = claim_dict["attachments"]
        attachments = (
            json.loads(raw) if isinstance(raw, str) else raw
        )
        if not attachments:
            return claim_dict

        storage = get_storage_adapter()
        claim_id = claim_dict.get("id", "")
        do_audit = (
            audit_presigned
            and repo is not None
            and actor_id is not None
            and isinstance(storage, S3StorageAdapter)
        )

        for attachment in attachments:
            url = attachment.get("url", "")
            if not url:
                continue
            if not _is_safe_attachment_url(url):
                attachment["url"] = "#"
                continue
            if url.startswith(("http://", "https://")):
                continue
            if isinstance(storage, LocalStorageAdapter):
                stored_name = url.split("/")[-1] if "/" in url else url
                attachment["url"] = f"/api/claims/{claim_id}/attachments/{stored_name}"
            else:
                storage_key = url
                attachment["url"] = storage.get_url(claim_id, url)
                if do_audit:
                    assert repo is not None and actor_id is not None
                    repo.insert_document_accessed_audit(
                        claim_id,
                        storage_key=storage_key,
                        actor_id=actor_id,
                        channel="adjuster_api",
                    )

        claim_dict["attachments"] = (
            json.dumps(attachments) if isinstance(raw, str) else attachments
        )
    except Exception as e:
        if do_audit:
            raise
        logger.warning(
            "Failed to resolve attachment URLs for claim %s: %s",
            claim_dict.get("id"),
            e,
        )

    return claim_dict


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
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List claims with optional filtering. Archived and purged claims are excluded by default."""
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

    _apply_adjuster_claim_filter(auth, conditions, params)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    params["limit"] = limit
    params["offset"] = offset
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}

    with get_connection() as conn:
        count_row = conn.execute(
            text(f"SELECT COUNT(*) as cnt FROM claims {where}"),
            count_params,
        ).fetchone()
        total = count_row[0] if count_row else 0

        rows = conn.execute(
            text(f"SELECT * FROM claims {where} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"),
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


class AssignBody(BaseModel):
    assignee: str = Field(..., min_length=1, description="Adjuster/user ID to assign")


class RejectBody(BaseModel):
    reason: str = ""


class RequestInfoBody(BaseModel):
    note: str = ""


class FollowUpRunBody(BaseModel):
    task: str = Field(..., min_length=1, description="Follow-up task (e.g., 'Gather photos from claimant')")
    user_response: Optional[str] = Field(default=None, description="Optional user response when recording in same run")


class RecordFollowUpResponseBody(BaseModel):
    message_id: int = Field(..., description="Follow-up message ID from send_user_message")
    response_content: str = Field(..., min_length=1, description="User's response text")


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


class PartyConsentUpdate(BaseModel):
    """Request body for PATCH /claims/{claim_id}/parties/{party_id}/consent."""

    consent_status: Literal["pending", "granted", "revoked"] = Field(
        ...,
        description="Data processing consent status. Revoked excludes party PII from LLM prompts.",
    )


@router.patch("/claims/{claim_id}/parties/{party_id}/consent", dependencies=[RequireAdjuster])
def update_party_consent(
    claim_id: str,
    party_id: int,
    body: PartyConsentUpdate,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Update data processing consent for a claim party. Revoked excludes party PII from LLM."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    parties = ctx.repo.get_claim_parties(claim_id)
    if not any(p.get("id") == party_id for p in parties):
        raise HTTPException(status_code=404, detail="Party not found")
    ctx.repo.update_claim_party(party_id, {"consent_status": body.consent_status})
    return {"claim_id": claim_id, "party_id": party_id, "consent_status": body.consent_status}


class CreatePartyRelationshipBody(BaseModel):
    """Request body for POST /claims/{claim_id}/party-relationships."""

    from_party_id: int = Field(..., ge=1, description="Subject party (edge tail)")
    to_party_id: int = Field(..., ge=1, description="Related party (edge head)")
    relationship_type: PartyRelationshipType = Field(..., description="Directed relationship type")


@router.post(
    "/claims/{claim_id}/party-relationships",
    dependencies=[RequireAdjuster],
    status_code=201,
)
def create_party_relationship(
    claim_id: str,
    body: CreatePartyRelationshipBody,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a directed party-to-party link (e.g. claimant represented_by attorney)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    try:
        rel_id = ctx.repo.add_claim_party_relationship(
            claim_id,
            body.from_party_id,
            body.to_party_id,
            body.relationship_type,
        )
    except DomainValidationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {
        "id": rel_id,
        "claim_id": claim_id,
        "from_party_id": body.from_party_id,
        "to_party_id": body.to_party_id,
        "relationship_type": body.relationship_type,
    }


@router.delete(
    "/claims/{claim_id}/party-relationships/{relationship_id}",
    dependencies=[RequireAdjuster],
    status_code=204,
)
def delete_party_relationship(
    claim_id: str,
    relationship_id: int,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Remove a party-to-party link for this claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    deleted = ctx.repo.delete_claim_party_relationship(claim_id, relationship_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Party relationship not found")


class CreatePortalTokenBody(BaseModel):
    """Optional party or email for the portal token."""

    party_id: Optional[int] = Field(None, description="Claim party ID (claimant/policyholder)")
    email: Optional[str] = Field(None, description="Email to associate with token")


class CreateRepairShopPortalTokenBody(BaseModel):
    """Optional shop identifier stored with the token (audit / repair_status.shop_id)."""

    shop_id: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Repair shop id or code; used when posting repair status if set",
    )


@router.post("/claims/{claim_id}/portal-token", dependencies=[RequireAdjuster])
def create_portal_token(
    request: Request,
    claim_id: str,
    body: CreatePortalTokenBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a claim access token for the claimant portal. Returns the raw token (send to claimant once)."""
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached

    try:
        ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
        if not get_settings().portal.enabled:
            raise HTTPException(status_code=503, detail="Claimant portal is disabled")
        email = body.email
        party_id = body.party_id
        if not email and party_id:
            parties = ctx.repo.get_claim_parties(claim_id)
            for p in parties:
                if p.get("id") == party_id:
                    email = p.get("email")
                    break
        if not email and not party_id:
            parties = ctx.repo.get_claim_parties(claim_id)
            for p in parties:
                if p.get("party_type") in ("claimant", "policyholder") and p.get("email"):
                    email = p.get("email")
                    party_id = p.get("id")
                    break
        token = create_claim_access_token(
            claim_id, party_id=party_id, email=email
        )
        result = {"claim_id": claim_id, "token": token}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.post("/claims/{claim_id}/repair-shop-portal-token", dependencies=[RequireAdjuster])
def create_repair_shop_portal_token(
    request: Request,
    claim_id: str,
    body: CreateRepairShopPortalTokenBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a repair shop access token for this claim. Returns the raw token once."""
    idem_key, cached = get_idempotency_key_and_cached(request)
    if cached is not None:
        return cached
    try:
        claim_row = ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
        if claim_row.get("claim_type") != "partial_loss":
            raise HTTPException(
                status_code=400,
                detail="Repair shop portal tokens are only issued for partial_loss claims",
            )
        if not get_settings().repair_shop_portal.enabled:
            raise HTTPException(status_code=503, detail="Repair shop portal is disabled")
        token = create_repair_shop_access_token(
            claim_id,
            shop_id=body.shop_id,
        )
        result = {"claim_id": claim_id, "token": token}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


@router.get("/claims/{claim_id}/attachments/{key}", dependencies=[RequireAdjuster])
def get_claim_attachment(
    claim_id: str,
    key: str,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Serve an attachment file for a claim. Local storage only; S3 uses presigned URLs.

    Appends a ``document_downloaded`` row to ``claim_audit_log`` (chain of custody).
    """
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))

    storage = get_storage_adapter()
    if not isinstance(storage, LocalStorageAdapter):
        raise HTTPException(
            status_code=404,
            detail="Attachment download is only available for local storage",
        )

    try:
        file_path = storage.get_path(claim_id, key)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid attachment key") from None
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Attachment not found: {key}")

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    ctx.repo.insert_document_download_audit(
        claim_id,
        storage_key=key,
        actor_id=actor_id,
        channel="adjuster_api",
    )
    return FileResponse(path=str(file_path), filename=key)


def _get_doc_repo():
    """Document repository with default db path."""
    return DocumentRepository(db_path=get_db_path())


def _maybe_update_document_request_on_receipt(
    doc_repo: DocumentRepository,
    claim_repo,
    claim_id: str,
    document_type: str,
) -> None:
    """When a document is received, update matching pending document_request and complete linked tasks."""
    pending = doc_repo.find_pending_document_requests_for_type(claim_id, document_type)
    if not pending:
        return
    req = pending[0]
    req_id = req.get("id")
    if not req_id:
        return
    doc_repo.update_document_request(
        req_id,
        status=DocumentRequestStatus.RECEIVED,
        received_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with get_connection() as conn:
        rows = conn.execute(
            text("SELECT id FROM claim_tasks WHERE document_request_id = :req_id AND status NOT IN ('completed', 'cancelled')"),
            {"req_id": req_id},
        ).fetchall()
        for row in rows:
            task_id = row_to_dict(row)["id"]
            claim_repo.update_task(task_id, status="completed", resolution_notes="Document received")


@router.get("/claims/{claim_id}/documents", dependencies=[RequireAdjuster])
def list_claim_documents(
    claim_id: str,
    document_type: Optional[str] = Query(None, description="Filter by document_type"),
    review_status: Optional[str] = Query(None, description="Filter by review_status"),
    group_by: Optional[str] = Query(
        None,
        description=(
            "If 'storage_key', response includes version_groups built from the first 500 matching "
            "rows (see version_groups_truncated when total exceeds 500)"
        ),
    ),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List documents for a claim with optional filters."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    gb = (group_by or "").strip().lower()
    if gb and gb != "storage_key":
        raise HTTPException(
            status_code=400,
            detail="Invalid group_by. Supported value: storage_key",
        )
    doc_repo = _get_doc_repo()
    documents, total = doc_repo.list_documents(
        claim_id, document_type=document_type, review_status=review_status, limit=limit, offset=offset
    )
    storage = get_storage_adapter()
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW

    def enrich_document_urls(docs: list[dict[str, Any]], insert_audit: bool = True) -> None:
        for doc in docs:
            sk = doc.get("storage_key", "")
            if sk:
                doc["url"] = storage.get_url(claim_id, sk)
                if insert_audit and isinstance(storage, S3StorageAdapter):
                    ctx.repo.insert_document_accessed_audit(
                        claim_id,
                        storage_key=sk,
                        actor_id=actor_id,
                        channel="adjuster_api",
                    )
            else:
                doc["url"] = None

    enrich_document_urls(documents)
    payload: dict[str, Any] = {
        "claim_id": claim_id,
        "documents": documents,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
    if gb == "storage_key":
        all_docs, docs_total = doc_repo.list_documents(
            claim_id,
            document_type=document_type,
            review_status=review_status,
            limit=500,
            offset=0,
        )
        enrich_document_urls(all_docs, insert_audit=False)
        payload["version_groups"] = build_document_version_groups(all_docs)
        payload["version_groups_truncated"] = docs_total > 500
    return payload


@router.post("/claims/{claim_id}/documents", dependencies=[RequireAdjuster])
async def upload_claim_document(
    claim_id: str,
    file: UploadFile = File(...),
    document_type: Optional[str] = Query(None, description="Document type (police_report, estimate, etc.)"),
    received_from: Optional[str] = Query(None, description="Source (claimant, repair_shop, etc.)"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Upload a document and create a claim_documents record."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename required")
    ext = (file.filename.rsplit(".", 1)[-1] or "").lower()
    if ext not in _ALLOWED_DOCUMENT_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type not allowed. Allowed: {', '.join(sorted(_ALLOWED_DOCUMENT_EXTENSIONS))}",
        )
    chunks: list[bytes] = []
    total_size = 0
    chunk_size = 1024 * 1024
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total_size += len(chunk)
        if total_size > _MAX_UPLOAD_SIZE_BYTES:
            raise HTTPException(status_code=413, detail="File exceeds maximum upload size")
        chunks.append(chunk)
    content = b"".join(chunks)
    if document_type is not None and document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {sorted(_VALID_DOCUMENT_TYPES)}",
        )
    storage = get_storage_adapter()
    stored_key = storage.save(claim_id=claim_id, filename=file.filename, content=content)
    doc_type = document_type or attachment_type_to_document_type(infer_attachment_type(file.filename)).value
    if doc_type not in _VALID_DOCUMENT_TYPES:
        doc_type = DocumentType.OTHER.value
    doc_repo = _get_doc_repo()
    doc_id = doc_repo.add_document(
        claim_id,
        stored_key,
        document_type=doc_type,
        received_from=received_from or "claimant",
    )
    _maybe_update_document_request_on_receipt(doc_repo, ctx.repo, claim_id, doc_type)
    doc = doc_repo.get_document(doc_id)
    if doc:
        doc["url"] = storage.get_url(claim_id, stored_key)
        if isinstance(storage, S3StorageAdapter):
            actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
            ctx.repo.insert_document_accessed_audit(
                claim_id,
                storage_key=stored_key,
                actor_id=actor_id,
                channel="adjuster_api",
            )
    return {"claim_id": claim_id, "document_id": doc_id, "document": doc}


class DocumentUpdateBody(BaseModel):
    """Body for PATCH /claims/{claim_id}/documents/{doc_id}."""

    review_status: Optional[str] = None
    document_type: Optional[str] = None
    privileged: Optional[bool] = None
    retention_date: Optional[str] = None


@router.patch("/claims/{claim_id}/documents/{doc_id}", dependencies=[RequireAdjuster])
def update_claim_document(
    claim_id: str,
    doc_id: int,
    body: DocumentUpdateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Update document metadata (review_status, privileged, etc.)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    doc_repo = _get_doc_repo()
    doc = doc_repo.get_document(doc_id)
    if doc is None or doc.get("claim_id") != claim_id:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}")
    review: ReviewStatus | None = None
    if body.review_status is not None:
        try:
            review = ReviewStatus(body.review_status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid review_status. Must be one of: {[s.value for s in ReviewStatus]}",
            )
    if body.document_type is not None and body.document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {sorted(_VALID_DOCUMENT_TYPES)}",
        )
    updated = doc_repo.update_document_review(
        doc_id,
        review_status=review,
        document_type=body.document_type,
        privileged=body.privileged,
        retention_date=body.retention_date,
    )
    return {"claim_id": claim_id, "document_id": doc_id, "document": updated}


@router.get("/claims/{claim_id}/document-requests", dependencies=[RequireAdjuster])
def list_document_requests(
    claim_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List document requests for a claim."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    doc_repo = _get_doc_repo()
    requests, total = doc_repo.list_document_requests(
        claim_id, status=status, limit=limit, offset=offset
    )
    return {"claim_id": claim_id, "requests": requests, "total": total, "limit": limit, "offset": offset}


class DocumentRequestCreateBody(BaseModel):
    """Body for POST /claims/{claim_id}/document-requests."""

    document_type: str = Field(..., min_length=1, description="Type requested (police_report, estimate, etc.)")
    requested_from: Optional[str] = Field(default=None, description="Party to request from")


@router.post("/claims/{claim_id}/document-requests", dependencies=[RequireAdjuster])
def create_document_request(
    claim_id: str,
    body: DocumentRequestCreateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a document request."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    if body.document_type not in _VALID_DOCUMENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {sorted(_VALID_DOCUMENT_TYPES)}",
        )
    doc_repo = _get_doc_repo()
    req_id = doc_repo.create_document_request(
        claim_id, body.document_type, requested_from=body.requested_from
    )
    req = doc_repo.get_document_request(req_id)
    return {"claim_id": claim_id, "request_id": req_id, "request": req}


class DocumentRequestUpdateBody(BaseModel):
    """Body for PATCH /claims/{claim_id}/document-requests/{req_id}."""

    status: Optional[str] = None
    received_at: Optional[str] = None


@router.patch("/claims/{claim_id}/document-requests/{req_id}", dependencies=[RequireAdjuster])
def update_document_request(
    claim_id: str,
    req_id: int,
    body: DocumentRequestUpdateBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Update document request (e.g. mark received)."""
    ensure_claim_access_for_adjuster(auth, claim_id, ctx.repo.get_claim(claim_id))
    doc_repo = _get_doc_repo()
    req = doc_repo.get_document_request(req_id)
    if req is None or req.get("claim_id") != claim_id:
        raise HTTPException(status_code=404, detail=f"Document request not found: {req_id}")
    status: DocumentRequestStatus | None = None
    if body.status is not None:
        try:
            status = DocumentRequestStatus(body.status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {[s.value for s in DocumentRequestStatus]}",
            )
    updated = doc_repo.update_document_request(
        req_id, status=status, received_at=body.received_at
    )
    return {"claim_id": claim_id, "request_id": req_id, "request": updated}


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
            async with _background_tasks_lock:
                if max_tasks > 0 and len(_background_tasks) >= max_tasks:
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
            result = await asyncio.to_thread(
                run_claim_workflow,
                claim_data_with_attachments,
                None,
                claim_id,
                actor_id=actor_id,
                ctx=ctx,
            )
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
            async with _background_tasks_lock:
                if max_tasks > 0 and len(_background_tasks) >= max_tasks:
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
            result = await asyncio.to_thread(
                run_claim_workflow,
                claim_data_with_attachments,
                None,
                claim_id,
                actor_id=actor_id,
                ctx=ctx,
            )
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


def _sanitize_incident_data(incident_dict: dict) -> dict:
    """Sanitize incident input data to prevent prompt injection and abuse.

    Applies sanitization to incident-level and vehicle-level claim data
    before creating claims via the incident repository.
    """
    sanitized: dict[str, Any] = {}
    
    # Sanitize incident-level fields
    for key, value in incident_dict.items():
        if key == "incident_description":
            sanitized[key] = sanitize_claim_data({"incident_description": value}).get("incident_description", "")
        elif key == "loss_state":
            sanitized[key] = sanitize_claim_data({"loss_state": value}).get("loss_state")
        elif key == "vehicles":
            # Sanitize each vehicle's claim data
            if isinstance(value, list):
                sanitized_vehicles = []
                for vehicle in value:
                    if isinstance(vehicle, dict):
                        # Convert vehicle to claim-like dict for sanitization
                        vehicle_claim_dict = {
                            "policy_number": vehicle.get("policy_number"),
                            "vin": vehicle.get("vin"),
                            "vehicle_year": vehicle.get("vehicle_year"),
                            "vehicle_make": vehicle.get("vehicle_make"),
                            "vehicle_model": vehicle.get("vehicle_model"),
                            "damage_description": vehicle.get("damage_description"),
                            "estimated_damage": vehicle.get("estimated_damage"),
                            "attachments": vehicle.get("attachments", []),
                            "loss_state": vehicle.get("loss_state"),
                            "parties": vehicle.get("parties", []),
                        }
                        sanitized_vehicle_dict = sanitize_claim_data(vehicle_claim_dict)
                        sanitized_vehicles.append(sanitized_vehicle_dict)
                sanitized[key] = sanitized_vehicles
            else:
                sanitized[key] = []
        else:
            sanitized[key] = value
    
    return sanitized


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
            max_tasks = get_settings().max_concurrent_background_tasks
            async with _background_tasks_lock:
                if max_tasks > 0 and len(_background_tasks) >= max_tasks:
                    release_idempotency_on_error(idem_key)
                    raise HTTPException(
                        status_code=503,
                        detail="Too many concurrent background tasks. Retry later.",
                        headers={"Retry-After": "60"},
                    )

        actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
        claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
            claim, files, actor_id, ctx=ctx,
        )

        if async_mode:
            _run_workflow_background(
                claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
            )
            result = {"claim_id": claim_id}
        else:
            result = await asyncio.to_thread(
                run_claim_workflow,
                claim_data_with_attachments,
                None,  # llm
                claim_id,  # existing_claim_id
                actor_id=actor_id,
                ctx=ctx,
            )
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


async def _process_claim_with_attachments(
    claim: str | ClaimInput,
    files: Optional[list[UploadFile]],
    actor_id: str,
    *,
    ctx: ClaimContext,
) -> tuple[str, dict]:
    """Shared helper for claim creation and attachment handling.

    Accepts either a JSON string (from form uploads) or an already-validated ClaimInput
    (from POST /api/claims JSON body). Sanitization and validation run once.

    Returns:
        tuple of (claim_id, claim_data_with_attachments)
    """
    if isinstance(claim, ClaimInput):
        claim_data = claim.model_dump()
    else:
        try:
            claim_data = json.loads(claim)
        except json.JSONDecodeError as e:
            raise HTTPException(status_code=400, detail=f"Invalid claim JSON: {e}") from e

    sanitized = sanitize_claim_data(claim_data)
    try:
        claim_input = ClaimInput.model_validate(sanitized)
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim data: {e}") from e

    repo = ctx.repo

    # Validate and buffer all file uploads BEFORE creating the claim record so
    # that a bad upload (oversized or empty) does not leave a dangling claim row.
    buffered_files: list[tuple[str, bytes, str | None]] = []
    if files:
        for f in files:
            if not f.filename:
                continue
            # Read in bounded chunks to enforce the size limit without loading
            # an arbitrarily large file into memory.
            chunks: list[bytes] = []
            total_size = 0
            chunk_size = 1024 * 1024  # 1 MB
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > _MAX_UPLOAD_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File '{f.filename}' exceeds the maximum upload size of {_MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB.",
                    )
                chunks.append(chunk)
            buffered_files.append((f.filename, b"".join(chunks), f.content_type))

    # Create claim record first, then store uploaded files.
    claim_id = repo.create_claim(claim_input, actor_id=actor_id)

    all_attachments = list(claim_input.attachments)
    doc_repo = DocumentRepository(db_path=get_db_path())
    if buffered_files:
        # Store uploaded files now that the claim record exists.
        storage = get_storage_adapter()
        for filename, content, content_type in buffered_files:
            stored_key = storage.save(
                claim_id=claim_id,
                filename=filename,
                content=content,
                content_type=content_type,
            )
            url = storage.get_url(claim_id, stored_key)
            if isinstance(storage, S3StorageAdapter):
                repo.insert_document_accessed_audit(
                    claim_id,
                    storage_key=stored_key,
                    actor_id=actor_id,
                    channel="adjuster_api",
                )
            atype = infer_attachment_type(filename)
            all_attachments.append(
                Attachment(url=url, type=atype, description=f"Uploaded: {filename}")
            )
            doc_type = attachment_type_to_document_type(atype)
            doc_repo.add_document(
                claim_id,
                stored_key,
                document_type=doc_type,
                received_from="claimant",
            )
            _maybe_update_document_request_on_receipt(doc_repo, repo, claim_id, doc_type.value)
        if all_attachments:
            repo.update_claim_attachments(claim_id, all_attachments, actor_id=actor_id)

    claim_data_with_attachments = _prepare_claim_for_workflow(
        claim_id, sanitized, all_attachments
    )
    return claim_id, claim_data_with_attachments


def _prepare_claim_for_workflow(
    claim_id: str,
    sanitized: dict,
    all_attachments: list,
) -> dict:
    """Build claim_data_with_attachments for run_claim_workflow."""
    attachments_for_workflow = []
    storage = get_storage_adapter()
    for a in all_attachments:
        url = a.url if hasattr(a, "url") else a.get("url", "")
        if isinstance(storage, LocalStorageAdapter) and url and not url.startswith(
            ("http://", "https://", "file://")
        ):
            path = storage.get_path(claim_id, url)
            if path.exists():
                url = f"file://{path.resolve()}"
        att = a.model_dump(mode="json") if hasattr(a, "model_dump") else a
        attachments_for_workflow.append({**att, "url": url})
    return {**sanitized, "attachments": attachments_for_workflow}


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
        max_tasks = get_settings().max_concurrent_background_tasks
        async with _background_tasks_lock:
            if max_tasks > 0 and len(_background_tasks) >= max_tasks:
                release_idempotency_on_error(idem_key)
                raise HTTPException(
                    status_code=503,
                    detail="Too many concurrent background tasks. Retry later.",
                    headers={"Retry-After": "60"},
                )
        actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
        claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
            claim, files, actor_id, ctx=ctx,
        )
        _run_workflow_background(
            claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
        )
        result = {"claim_id": claim_id}
        store_response_if_idempotent(idem_key, 200, result)
        return result
    except Exception:
        release_idempotency_on_error(idem_key)
        raise


async def _stream_claim_updates(claim_id: str):
    """SSE generator: poll claim, history, workflows and yield updates."""
    elapsed = 0.0

    def _fetch_claim_snapshot():
        """Fetch claim + audit log + workflow runs + stage progress in one DB transaction.

        Intended to be called via asyncio.to_thread so that SQLite access
        does not block the event loop.
        """
        db_path = get_db_path()
        with get_connection(db_path) as conn:
            claim_row = conn.execute(
                text("SELECT * FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if claim_row is None:
                return None, None, None, None

            claim_dict = row_to_dict(claim_row)
            _resolve_attachment_urls(claim_dict)

            history_rows = conn.execute(
                text("SELECT id, claim_id, action, old_status, new_status, details, actor_id, created_at "
                     "FROM claim_audit_log WHERE claim_id = :claim_id ORDER BY id ASC"),
                {"claim_id": claim_id},
            ).fetchall()

            wf_rows = conn.execute(
                text("SELECT * FROM workflow_runs WHERE claim_id = :claim_id ORDER BY id ASC"),
                {"claim_id": claim_id},
            ).fetchall()

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
            completed_stages = []
            for r in cp_rows:
                d = row_to_dict(r)
                sk = d["stage_key"]
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

        return claim_dict, history_rows, wf_rows, completed_stages

    while elapsed < _STREAM_MAX_DURATION:
        result = await asyncio.to_thread(_fetch_claim_snapshot)
        claim_dict, history_rows, wf_rows, completed_stages = result
        if claim_dict is None:
            yield f"data: {json.dumps({'error': 'Claim not found'})}\n\n"
            return

        payload = {
            "claim": claim_dict,
            "history": [row_to_dict(r) for r in history_rows],
            "workflows": [row_to_dict(r) for r in wf_rows],
            "progress": completed_stages or [],
        }
        yield f"data: {json.dumps(payload)}\n\n"

        status = claim_dict.get("status") or ""
        if status not in (STATUS_PENDING, STATUS_PROCESSING):
            yield f"data: {json.dumps({'done': True, 'status': status})}\n\n"
            return

        await asyncio.sleep(_STREAM_POLL_INTERVAL)
        elapsed += _STREAM_POLL_INTERVAL

    yield f"data: {json.dumps({'error': 'Stream timeout', 'elapsed': elapsed})}\n\n"


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


@router.post("/claims/{claim_id}/reprocess")
async def reprocess_claim(
    claim_id: str,
    from_stage: Optional[str] = Query(None, description="Resume from this stage (router, escalation_check, workflow, settlement)"),
    auth: AuthContext = RequireSupervisor,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Re-run workflow for an existing claim. Requires supervisor role.

    Pass ``from_stage`` to resume from a specific stage using checkpoints from
    the most recent workflow run.
    """
    from claim_agent.crews.main_crew import WORKFLOW_STAGES

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
    result = await asyncio.to_thread(
        run_claim_workflow,
        claim_data,
        existing_claim_id=claim_id,
        actor_id=actor_id,
        resume_run_id=resume_run_id,
        from_stage=from_stage,
        ctx=ctx,
    )
    return result


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
    from claim_agent.workflow.claim_review_orchestrator import run_claim_review as _run_claim_review

    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    actor_id = auth.identity if auth.identity != "anonymous" else "claim_review_crew"
    report = await asyncio.to_thread(
        _run_claim_review,
        claim_id,
        actor_id=actor_id,
        ctx=ctx,
    )

    report_json = report.model_dump_json()
    ctx.repo.record_claim_review(claim_id, report_json, actor_id)

    return report.model_dump(mode="json")
