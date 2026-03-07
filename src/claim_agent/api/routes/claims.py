"""Claims API routes: listing, detail, audit log, workflow runs, statistics."""

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.constants import (
    STATUS_ARCHIVED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_PROCESSING,
)
from claim_agent.db.database import get_connection, get_db_path
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import Attachment, ClaimInput
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.utils import infer_attachment_type
from claim_agent.utils.sanitization import sanitize_claim_data

logger = logging.getLogger(__name__)

router = APIRouter(tags=["claims"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin")
RequireSupervisor = require_role("supervisor", "admin")

_MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

_STREAM_POLL_INTERVAL = 1.0  # seconds between DB polls
_STREAM_MAX_DURATION = 300  # 5 min timeout

PRIORITY_VALUES = ("critical", "high", "medium", "low")

_background_tasks: set[asyncio.Task] = set()


def _run_workflow_background(
    claim_id: str,
    claim_data_with_attachments: dict,
    actor_id: str,
) -> asyncio.Task:
    """Run claim workflow in background. Returns task for tracking."""
    async def run_in_thread():
        try:
            await asyncio.to_thread(
                run_claim_workflow,
                claim_data_with_attachments,
                None,
                claim_id,
                actor_id=actor_id,
            )
        except Exception:
            logger.exception(
                "Unhandled exception in background workflow for claim_id %s", claim_id
            )
            try:
                _repo = ClaimRepository(db_path=get_db_path())
                _repo.update_claim_status(
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
):
    """List claims with status needs_review for the adjuster workflow."""
    if priority is not None and priority not in PRIORITY_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority: {priority}. Must be one of: {', '.join(PRIORITY_VALUES)}",
        )
    repo = ClaimRepository(db_path=get_db_path())
    claims, total = repo.list_claims_needing_review(
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


@router.patch("/claims/{claim_id}/assign")
def assign_claim(
    claim_id: str,
    body: AssignBody = Body(...),
    auth: AuthContext = RequireAdjuster,
):
    """Assign claim to an adjuster."""
    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        repo.assign_claim(claim_id, body.assignee, actor_id=actor_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "assignee": body.assignee}


@router.post("/claims/{claim_id}/review/approve")
async def approve_review(
    claim_id: str,
    auth: AuthContext = RequireSupervisor,
):
    """Approve claim for continued processing and re-run workflow. Requires supervisor."""
    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    claim_data = claim_data_from_row(claim)
    try:
        ClaimInput.model_validate(claim_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim data for reprocess: {e}") from e
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        repo.perform_adjuster_action(claim_id, "approve", actor_id=actor_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    result = run_claim_workflow(
        claim_data,
        existing_claim_id=claim_id,
        actor_id=actor_id,
    )
    return result


@router.post("/claims/{claim_id}/review/reject")
def reject_review(
    claim_id: str,
    body: RejectBody = Body(default=RejectBody()),
    auth: AuthContext = RequireAdjuster,
):
    """Reject claim with optional reason."""
    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        repo.perform_adjuster_action(claim_id, "reject", actor_id=actor_id, reason=body.reason)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "status": "denied"}


@router.post("/claims/{claim_id}/review/request-info")
def request_info_review(
    claim_id: str,
    body: RequestInfoBody = Body(default=RequestInfoBody()),
    auth: AuthContext = RequireAdjuster,
):
    """Request more information from claimant."""
    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        repo.perform_adjuster_action(claim_id, "request_info", actor_id=actor_id, note=body.note)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "status": "pending_info"}


@router.post("/claims/{claim_id}/review/escalate-to-siu")
def escalate_to_siu(
    claim_id: str,
    auth: AuthContext = RequireAdjuster,
):
    """Escalate claim to Special Investigations Unit."""
    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        repo.perform_adjuster_action(claim_id, "escalate_to_siu", actor_id=actor_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"claim_id": claim_id, "status": "under_investigation"}


@router.get("/claims/{claim_id}", dependencies=[RequireAdjuster])
def get_claim(claim_id: str):
    """Get a single claim by ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    return _resolve_attachment_urls(dict(row))


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
def get_claim_history(claim_id: str):
    """Get audit log entries for a claim."""
    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    history = repo.get_claim_history(claim_id)
    return {"claim_id": claim_id, "history": history}


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
):
    """Submit a new claim for processing. Accepts ClaimInput JSON body.

    Use for programmatic access: portals, batch ingestion, third-party integrations.
    For file uploads, use POST /claims/process with multipart form.
    """
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    sanitized = sanitize_claim_data(claim_input.model_dump(mode="json"))
    claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
        json.dumps(sanitized), None, actor_id
    )

    if async_mode:
        _run_workflow_background(
            claim_id, claim_data_with_attachments, actor_id
        )
        return {"claim_id": claim_id}

    result = await asyncio.to_thread(
        run_claim_workflow,
        claim_data_with_attachments,
        None,
        claim_id,
        actor_id=actor_id,
    )
    return result


@router.post("/claims/process")
async def process_claim(
    claim: str = Form(..., description="Claim data as JSON string"),
    files: Optional[list[UploadFile]] = File(default=None, description="Optional attachment files"),
    auth: AuthContext = RequireAdjuster,
):
    """Submit a new claim for processing. Accepts claim JSON and optional file uploads.

    - claim: JSON string with policy_number, vin, vehicle_year, vehicle_make, vehicle_model,
      incident_date, incident_description, damage_description, estimated_damage (optional),
      attachments (optional list of {url, type, description}).
    - files: Optional multipart files (photos, PDFs, estimates). Stored via configured backend.
    """
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
        claim, files, actor_id
    )
    result = await asyncio.to_thread(
        run_claim_workflow,
        claim_data_with_attachments,
        None,  # llm
        claim_id,  # existing_claim_id
        actor_id=actor_id,
    )
    return result


async def _process_claim_with_attachments(
    claim: str,
    files: Optional[list[UploadFile]],
    actor_id: str,
) -> tuple[str, dict]:
    """Shared helper for claim creation and attachment handling.
    
    Returns:
        tuple of (claim_id, claim_data_with_attachments)
    """
    try:
        claim_data = json.loads(claim)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim JSON: {e}") from e

    sanitized = sanitize_claim_data(claim_data)
    try:
        claim_input = ClaimInput.model_validate(sanitized)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim data: {e}") from e

    repo = ClaimRepository(db_path=get_db_path())

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
):
    """Submit a new claim for async processing. Returns claim_id immediately; workflow runs in background.
    Use GET /claims/{claim_id}/stream to receive realtime updates."""
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    claim_id, claim_data_with_attachments = await _process_claim_with_attachments(
        claim, files, actor_id
    )
    _run_workflow_background(
        claim_id, claim_data_with_attachments, actor_id
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
):
    """Server-Sent Events stream of claim status, audit log, and workflow runs.
    Polls every second until claim status is no longer pending/processing."""
    repo = ClaimRepository(db_path=get_db_path())
    if repo.get_claim(claim_id) is None:
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


@router.post("/claims/{claim_id}/reprocess")
async def reprocess_claim(
    claim_id: str,
    from_stage: Optional[str] = Query(None, description="Resume from this stage (router, escalation_check, workflow, settlement)"),
    auth: AuthContext = RequireSupervisor,
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

    repo = ClaimRepository(db_path=get_db_path())
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")

    claim_data = claim_data_from_row(claim)
    try:
        ClaimInput.model_validate(claim_data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid claim data for reprocess: {e}") from e

    resume_run_id: str | None = None
    if from_stage is not None:
        resume_run_id = repo.get_latest_checkpointed_run_id(claim_id)
        if resume_run_id is None:
            from_stage = None

    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    result = run_claim_workflow(
        claim_data,
        existing_claim_id=claim_id,
        actor_id=actor_id,
        resume_run_id=resume_run_id,
        from_stage=from_stage,
    )
    return result
