"""Claims API routes: listing, detail, audit log, workflow runs, statistics."""

import asyncio
import json
import logging
import math
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.workflow.handback_orchestrator import run_handback_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.constants import (
    DENIAL_COVERAGE_STATUSES,
    DISPUTABLE_STATUSES,
    STATUS_ARCHIVED,
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PROCESSING,
    SUPPLEMENTABLE_STATUSES,
)
from claim_agent.db.database import get_connection, get_db_path
from claim_agent.models.claim import Attachment, ClaimInput
from claim_agent.models.dispute import DisputeType
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.utils import infer_attachment_type
from claim_agent.rag.constants import normalize_state
from claim_agent.utils.sanitization import (
    MAX_ACTOR_ID,
    MAX_DENIAL_REASON,
    MAX_PAYOUT,
    MAX_POLICYHOLDER_EVIDENCE,
    sanitize_claim_data,
)
from claim_agent.workflow.denial_coverage_orchestrator import run_denial_coverage_workflow
from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow
from claim_agent.workflow.supplemental_orchestrator import run_supplemental_workflow

logger = logging.getLogger(__name__)


def get_claim_context() -> ClaimContext:
    """FastAPI dependency providing a per-request ClaimContext."""
    return ClaimContext.from_defaults(db_path=get_db_path())

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin")
RequireSupervisor = require_role("supervisor", "admin")

_MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

_STREAM_POLL_INTERVAL = 1.0  # seconds between DB polls
_STREAM_MAX_DURATION = 300  # 5 min timeout

PRIORITY_VALUES = ("critical", "high", "medium", "low")

_background_tasks: set[asyncio.Task] = set()

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
                )
            except Exception:
                logger.exception(
                    "Failed to mark claim %s as failed after workflow error", claim_id
                )

    task = asyncio.create_task(run_in_thread())
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def _resolve_attachment_urls(claim_dict: dict) -> dict:
    """Convert storage keys to fetchable URLs: presigned for S3, download endpoint for local."""
    if "attachments" not in claim_dict or not claim_dict["attachments"]:
        return claim_dict

    try:
        raw = claim_dict["attachments"]
        attachments = (
            json.loads(raw) if isinstance(raw, str) else raw
        )
        if not attachments:
            return claim_dict

        storage = get_storage_adapter()
        claim_id = claim_dict.get("id", "")

        for attachment in attachments:
            url = attachment.get("url", "")
            if not url or url.startswith(("http://", "https://")):
                continue
            if isinstance(storage, LocalStorageAdapter):
                stored_name = url.split("/")[-1] if "/" in url else url
                attachment["url"] = f"/api/claims/{claim_id}/attachments/{stored_name}"
            else:
                attachment["url"] = storage.get_url(claim_id, url)

        claim_dict["attachments"] = (
            json.dumps(attachments) if isinstance(raw, str) else attachments
        )
    except Exception as e:
        logger.warning(
            "Failed to resolve attachment URLs for claim %s: %s",
            claim_dict.get("id"),
            e,
        )

    return claim_dict


@router.get("/claims/stats", dependencies=[RequireAdjuster])
def get_claims_stats():
    """Aggregate statistics: count by status, count by type, totals."""
    with get_connection() as conn:
        # Total count
        total = conn.execute("SELECT COUNT(*) as cnt FROM claims").fetchone()["cnt"]

        # By status
        rows = conn.execute(
            "SELECT COALESCE(status, 'unknown') as status, COUNT(*) as cnt "
            "FROM claims GROUP BY status ORDER BY cnt DESC"
        ).fetchall()
        by_status = {r["status"]: r["cnt"] for r in rows}

        # By type
        rows = conn.execute(
            "SELECT COALESCE(claim_type, 'unclassified') as claim_type, COUNT(*) as cnt "
            "FROM claims GROUP BY claim_type ORDER BY cnt DESC"
        ).fetchall()
        by_type = {r["claim_type"]: r["cnt"] for r in rows}

        # Date range
        date_row = conn.execute(
            "SELECT MIN(created_at) as earliest, MAX(created_at) as latest FROM claims"
        ).fetchone()

        # Recent audit events count
        audit_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM claim_audit_log"
        ).fetchone()["cnt"]

        # Workflow runs count
        workflow_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM workflow_runs"
        ).fetchone()["cnt"]

    return {
        "total_claims": total,
        "by_status": by_status,
        "by_type": by_type,
        "earliest_claim": date_row["earliest"],
        "latest_claim": date_row["latest"],
        "total_audit_events": audit_count,
        "total_workflow_runs": workflow_count,
    }


@router.get("/claims", dependencies=[RequireAdjuster])
def list_claims(
    status: Optional[str] = Query(None, description="Filter by status"),
    claim_type: Optional[str] = Query(None, description="Filter by claim type"),
    include_archived: bool = Query(False, description="Include archived claims (retention)"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List claims with optional filtering. Archived claims are excluded by default."""
    conditions = []
    params: list = []

    if status:
        conditions.append("status = ?")
        params.append(status)
    if not include_archived and (status is None or status != STATUS_ARCHIVED):
        conditions.append("status != ?")
        params.append(STATUS_ARCHIVED)
    if claim_type:
        conditions.append("claim_type = ?")
        params.append(claim_type)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    with get_connection() as conn:
        # Get total for pagination
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM claims {where}", params
        ).fetchone()
        total = count_row["cnt"]

        rows = conn.execute(
            f"SELECT * FROM claims {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()

    return {
        "claims": [_resolve_attachment_urls(dict(r)) for r in rows],
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
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List claims with status needs_review for the adjuster workflow."""
    if priority is not None and priority not in PRIORITY_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority: {priority}. Must be one of: {', '.join(PRIORITY_VALUES)}",
        )
    claims, total = ctx.repo.list_claims_needing_review(
        assignee=assignee,
        priority=priority,
        older_than_hours=older_than_hours,
        limit=limit,
        offset=offset,
    )
    return {
        "claims": [_resolve_attachment_urls(c) for c in claims],
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
    auth: AuthContext = RequireAdjuster,
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
        except Exception as e:
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
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
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
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
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
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        ctx.adjuster_service.escalate_to_siu(claim_id, actor_id=actor_id)
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "status": "under_investigation"}


@router.get("/claims/{claim_id}", dependencies=[RequireAdjuster])
def get_claim(claim_id: str, ctx: ClaimContext = Depends(get_claim_context)):
    """Get a single claim by ID. Includes claim notes for cross-crew context."""
    row = ctx.repo.get_claim(claim_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    result = _resolve_attachment_urls(row)
    result["notes"] = ctx.repo.get_notes(claim_id)
    return result


@router.get("/claims/{claim_id}/attachments/{key}", dependencies=[RequireAdjuster])
def get_claim_attachment(claim_id: str, key: str):
    """Serve an attachment file for a claim. Local storage only; S3 uses presigned URLs."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    storage = get_storage_adapter()
    if not isinstance(storage, LocalStorageAdapter):
        raise HTTPException(
            status_code=404,
            detail="Attachment download is only available for local storage",
        )

    file_path = storage.get_path(claim_id, key)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Attachment not found: {key}")

    return FileResponse(path=str(file_path), filename=key)


@router.get("/claims/{claim_id}/history", dependencies=[RequireAdjuster])
def get_claim_history(claim_id: str, ctx: ClaimContext = Depends(get_claim_context)):
    """Get audit log entries for a claim."""
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    history = ctx.repo.get_claim_history(claim_id)
    return {"claim_id": claim_id, "history": history}


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
def get_claim_notes(claim_id: str, ctx: ClaimContext = Depends(get_claim_context)):
    """List notes for a claim, ordered by created_at."""
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    notes = ctx.repo.get_notes(claim_id)
    return {"claim_id": claim_id, "notes": notes}


@router.post("/claims/{claim_id}/notes", dependencies=[RequireAdjuster])
def add_claim_note(
    claim_id: str,
    body: AddNoteBody = Body(...),
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Add a note to a claim."""
    try:
        ctx.repo.add_note(claim_id, body.note, body.actor_id)
    except ClaimNotFoundError:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}") from None
    return {"claim_id": claim_id, "actor_id": body.actor_id}


@router.get("/claims/{claim_id}/workflows", dependencies=[RequireAdjuster])
def get_claim_workflows(claim_id: str):
    """Get workflow runs for a claim."""
    with get_connection() as conn:
        # Verify claim exists
        claim = conn.execute(
            "SELECT id FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        if claim is None:
            raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

        rows = conn.execute(
            "SELECT * FROM workflow_runs WHERE claim_id = ? ORDER BY id ASC",
            (claim_id,),
        ).fetchall()

    return {"claim_id": claim_id, "workflows": [dict(r) for r in rows]}


@router.post("/claims")
async def create_claim(
    claim_input: ClaimInput = Body(..., description="Claim data as JSON"),
    async_mode: bool = Query(False, alias="async", description="If true, return claim_id immediately and process in background"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Submit a new claim for processing. Accepts ClaimInput JSON body.

    Use for programmatic access: portals, batch ingestion, third-party integrations.
    For file uploads, use POST /api/claims/process with multipart form.
    """
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
        claim_input, None, actor_id, ctx=ctx,
    )

    if async_mode:
        _run_workflow_background(
            claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
        )
        return {"claim_id": claim_id}

    result = await asyncio.to_thread(
        run_claim_workflow,
        claim_data_with_attachments,
        None,
        claim_id,
        actor_id=actor_id,
        ctx=ctx,
    )
    return result


@router.post("/claims/process")
async def process_claim(
    claim: str = Form(..., description="Claim data as JSON string"),
    files: Optional[list[UploadFile]] = File(default=None, description="Optional attachment files"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Submit a new claim for processing. Accepts claim JSON and optional file uploads.

    - claim: JSON string with policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
      incident_date, incident_description, damage_description, estimated_damage (optional),
      attachments (optional list of {url, type, description}).
    - files: Optional multipart files (photos, PDFs, estimates). Stored via configured backend.
    """
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
        claim, files, actor_id, ctx=ctx,
    )
    result = await asyncio.to_thread(
        run_claim_workflow,
        claim_data_with_attachments,
        None,  # llm
        claim_id,  # existing_claim_id
        actor_id=actor_id,
        ctx=ctx,
    )
    return result


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
    except Exception as e:
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
            atype = infer_attachment_type(filename)
            all_attachments.append(
                Attachment(url=url, type=atype, description=f"Uploaded: {filename}")
            )
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
    claim: str = Form(..., description="Claim data as JSON string"),
    files: Optional[list[UploadFile]] = File(default=None, description="Optional attachment files"),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Submit a new claim for async processing. Returns claim_id immediately; workflow runs in background.
    Use GET /claims/{claim_id}/stream to receive realtime updates."""
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
        claim, files, actor_id, ctx=ctx,
    )
    _run_workflow_background(
        claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
    )
    return {"claim_id": claim_id}


async def _stream_claim_updates(claim_id: str):
    """SSE generator: poll claim, history, workflows and yield updates."""
    elapsed = 0.0

    def _fetch_claim_snapshot():
        """Fetch claim + audit log + workflow runs in one DB transaction.

        Intended to be called via asyncio.to_thread so that SQLite access
        does not block the event loop.
        """
        db_path = get_db_path()
        with get_connection(db_path) as conn:
            claim_row = conn.execute(
                "SELECT * FROM claims WHERE id = ?", (claim_id,)
            ).fetchone()
            if claim_row is None:
                return None, None, None

            claim_dict = dict(claim_row)
            _resolve_attachment_urls(claim_dict)

            history_rows = conn.execute(
                """SELECT id, claim_id, action, old_status, new_status, details, actor_id, created_at
                   FROM claim_audit_log WHERE claim_id = ? ORDER BY id ASC""",
                (claim_id,),
            ).fetchall()

            wf_rows = conn.execute(
                "SELECT * FROM workflow_runs WHERE claim_id = ? ORDER BY id ASC",
                (claim_id,),
            ).fetchall()

        return claim_dict, history_rows, wf_rows

    while elapsed < _STREAM_MAX_DURATION:
        claim_dict, history_rows, wf_rows = await asyncio.to_thread(_fetch_claim_snapshot)
        if claim_dict is None:
            yield f"data: {json.dumps({'error': 'Claim not found'})}\n\n"
            return

        payload = {
            "claim": claim_dict,
            "history": [dict(r) for r in history_rows],
            "workflows": [dict(r) for r in wf_rows],
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
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
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
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

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
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

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
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    claim_type = claim.get("claim_type")
    if claim_type != "partial_loss":
        raise HTTPException(
            status_code=400,
            detail=f"Supplemental only applies to partial_loss claims. Claim has claim_type={claim_type!r}.",
        )

    claim_status = claim.get("status")
    if claim_status not in SUPPLEMENTABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Claim cannot receive supplemental in status {claim_status!r}. "
                f"Allowed statuses: {', '.join(SUPPLEMENTABLE_STATUSES)}."
            ),
        )

    supplemental_data = {
        "claim_id": claim_id,
        "supplemental_damage_description": body.supplemental_damage_description,
        "reported_by": body.reported_by,
    }

    try:
        result = await asyncio.to_thread(
            run_supplemental_workflow,
            supplemental_data,
            ctx=ctx,
        )
        return result
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


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
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim data for reprocess: {e}") from e

    resume_run_id: str | None = None
    if from_stage is not None:
        resume_run_id = ctx.repo.get_latest_checkpointed_run_id(claim_id)
        if resume_run_id is None:
            from_stage = None

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    result = run_claim_workflow(
        claim_data,
        existing_claim_id=claim_id,
        actor_id=actor_id,
        resume_run_id=resume_run_id,
        from_stage=from_stage,
        ctx=ctx,
    )
    return result
