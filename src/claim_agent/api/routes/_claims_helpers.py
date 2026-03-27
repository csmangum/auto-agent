"""Shared helper functions and constants for claims routes.

HTTP ``Retry-After`` hints: ``CLAIM_ALREADY_PROCESSING_RETRY_AFTER`` (409),
``BACKGROUND_QUEUE_FULL_RETRY_AFTER`` (503 when the background workflow queue is full).
"""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, NoReturn

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import text

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import adjuster_identity_scopes_assignee
from claim_agent.config import get_settings
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.constants import (
    STATUS_FAILED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING,
    STATUS_PROCESSING,
)
from claim_agent.db.database import get_connection, get_db_path, row_to_dict
from claim_agent.db.document_repository import DocumentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimAlreadyProcessingError, InvalidClaimTransitionError
from claim_agent.models.claim import Attachment, ClaimInput
from claim_agent.models.document import DocumentRequestStatus, DocumentType
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.utils import attachment_type_to_document_type, infer_attachment_type
from claim_agent.utils.sanitization import is_safe_attachment_url, sanitize_claim_data
from claim_agent.workflow.helpers import WORKFLOW_STAGES

logger = logging.getLogger(__name__)

CLAIM_ALREADY_PROCESSING_RETRY_AFTER = "30"
BACKGROUND_QUEUE_FULL_RETRY_AFTER = "60"

ALLOWED_DOCUMENT_EXTENSIONS = frozenset(
    {"pdf", "jpg", "jpeg", "png", "gif", "webp", "heic", "doc", "docx", "xls", "xlsx"}
)

VALID_DOCUMENT_TYPES = frozenset(dt.value for dt in DocumentType)

STREAM_POLL_INTERVAL = 1.0
STREAM_MAX_DURATION = 300

PRIORITY_VALUES = ("critical", "high", "medium", "low")

ALLOWED_SORT_FIELDS = frozenset({
    "created_at",
    "updated_at",
    "incident_date",
    "estimated_damage",
    "payout_amount",
    "status",
    "claim_type",
    "policy_number",
})

background_tasks: set[asyncio.Task] = set()
background_tasks_lock = asyncio.Lock()
task_claim_ids: dict[asyncio.Task, str] = {}

approve_locks: dict[str, asyncio.Lock] = {}
approve_locks_lock = asyncio.Lock()
MAX_APPROVE_LOCKS = 10000


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


def http_already_processing(exc: ClaimAlreadyProcessingError) -> NoReturn:
    """Raise HTTP 409 for concurrent workflow; never returns."""
    raise HTTPException(
        status_code=409,
        detail=str(exc),
        headers={"Retry-After": CLAIM_ALREADY_PROCESSING_RETRY_AFTER},
    ) from exc


def max_upload_file_size_bytes() -> int:
    """Per-file upload cap from settings (MAX_UPLOAD_FILE_SIZE_MB)."""
    return get_settings().max_upload_file_size_mb * 1024 * 1024


def upload_file_size_exceeded_detail() -> str:
    """HTTP 413 detail for per-file upload limit (shared by claims and portal routes)."""
    mb = get_settings().max_upload_file_size_mb
    return f"File exceeds the maximum upload size of {mb} MB."


def adjuster_scope_params(auth: AuthContext) -> dict[str, Any]:
    """Query params for adjuster-only claim scoping (assignee matches JWT sub / API key identity)."""
    if not adjuster_identity_scopes_assignee(auth):
        return {}
    return {"_scope_assignee": auth.identity}


def apply_adjuster_claim_filter(
    auth: AuthContext, conditions: list[str], params: dict[str, Any]
) -> None:
    if adjuster_identity_scopes_assignee(auth):
        conditions.append("assignee = :_scope_assignee")
        params["_scope_assignee"] = auth.identity


async def get_approve_lock(claim_id: str) -> asyncio.Lock:
    """Get or create a lock for the given claim_id."""
    async with approve_locks_lock:
        if claim_id not in approve_locks:
            if len(approve_locks) >= MAX_APPROVE_LOCKS:
                approve_locks.pop(next(iter(approve_locks)))
            approve_locks[claim_id] = asyncio.Lock()
        return approve_locks[claim_id]


def run_workflow_background(
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
        except ClaimAlreadyProcessingError:
            logger.warning(
                "Claim %s is already being processed; background workflow skipped",
                claim_id,
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
    background_tasks.add(task)
    task_claim_ids[task] = claim_id

    def _on_done(t: asyncio.Task) -> None:
        background_tasks.discard(t)
        task_claim_ids.pop(t, None)

    task.add_done_callback(_on_done)
    return task


def _background_workflow_queue_at_capacity_unlocked() -> bool:
    """Whether the background task set is full (caller must hold ``background_tasks_lock``)."""
    max_tasks = get_settings().max_concurrent_background_tasks
    return max_tasks > 0 and len(background_tasks) >= max_tasks


async def background_workflow_queue_full() -> bool:
    """True when starting another background workflow would exceed the configured limit."""
    async with background_tasks_lock:
        return _background_workflow_queue_at_capacity_unlocked()


async def try_run_workflow_background(
    claim_id: str,
    claim_data_with_attachments: dict,
    actor_id: str,
    ctx: ClaimContext | None = None,
) -> asyncio.Task | None:
    """Run claim workflow in background if under concurrent limit. Returns None when at capacity."""
    async with background_tasks_lock:
        if _background_workflow_queue_at_capacity_unlocked():
            return None
        return run_workflow_background(
            claim_id, claim_data_with_attachments, actor_id, ctx=ctx,
        )


def resolve_attachment_urls(
    claim_dict: dict,
    *,
    repo: ClaimRepository | None = None,
    actor_id: str | None = None,
    audit_presigned: bool = False,
) -> dict:
    """Convert storage keys to fetchable URLs: presigned for S3, download endpoint for local."""
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
            if not is_safe_attachment_url(url):
                attachment["url"] = "#"
                continue
            if url.startswith(("http://", "https://")):
                continue
            if isinstance(storage, LocalStorageAdapter):
                stored_name = url.split("/")[-1] if "/" in url else url
                attachment["url"] = f"/api/v1/claims/{claim_id}/attachments/{stored_name}"
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


def get_doc_repo():
    """Document repository with default db path."""
    return DocumentRepository(db_path=get_db_path())


def maybe_update_document_request_on_receipt(
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


def sanitize_incident_data(incident_dict: dict) -> dict:
    """Sanitize incident input data to prevent prompt injection and abuse."""
    sanitized: dict[str, Any] = {}

    for key, value in incident_dict.items():
        if key == "incident_description":
            sanitized[key] = sanitize_claim_data({"incident_description": value}).get("incident_description", "")
        elif key == "loss_state":
            sanitized[key] = sanitize_claim_data({"loss_state": value}).get("loss_state")
        elif key == "vehicles":
            if isinstance(value, list):
                sanitized_vehicles = []
                for vehicle in value:
                    if isinstance(vehicle, dict):
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


async def process_claim_with_attachments(
    claim: str | ClaimInput,
    files: list[UploadFile] | None,
    actor_id: str,
    *,
    ctx: ClaimContext,
) -> tuple[str, dict]:
    """Shared helper for claim creation and attachment handling.

    Returns: tuple of (claim_id, claim_data_with_attachments)
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

    buffered_files: list[tuple[str, bytes, str | None]] = []
    if files:
        for f in files:
            if not f.filename:
                continue
            chunks: list[bytes] = []
            total_size = 0
            chunk_size = 1024 * 1024
            while True:
                chunk = await f.read(chunk_size)
                if not chunk:
                    break
                total_size += len(chunk)
                if total_size > max_upload_file_size_bytes():
                    max_mb = get_settings().max_upload_file_size_mb
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File '{f.filename}' exceeds the maximum upload size of {max_mb} MB."
                        ),
                    )
                chunks.append(chunk)
            buffered_files.append((f.filename, b"".join(chunks), f.content_type))

    claim_id = repo.create_claim(claim_input, actor_id=actor_id)

    all_attachments = list(claim_input.attachments)
    doc_repo = DocumentRepository(db_path=get_db_path())
    if buffered_files:
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
            maybe_update_document_request_on_receipt(doc_repo, repo, claim_id, doc_type.value)
        if all_attachments:
            repo.update_claim_attachments(claim_id, all_attachments, actor_id=actor_id)

    claim_data_with_attachments = prepare_claim_for_workflow(
        claim_id, sanitized, all_attachments
    )
    return claim_id, claim_data_with_attachments


def prepare_claim_for_workflow(
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


async def stream_claim_updates(claim_id: str):
    """SSE generator: poll claim, history, workflows and yield updates."""
    elapsed = 0.0

    def _fetch_claim_snapshot():
        db_path = get_db_path()
        with get_connection(db_path) as conn:
            claim_row = conn.execute(
                text("SELECT * FROM claims WHERE id = :claim_id"),
                {"claim_id": claim_id},
            ).fetchone()
            if claim_row is None:
                return None, None, None, None

            claim_dict = row_to_dict(claim_row)
            resolve_attachment_urls(claim_dict)

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

    while elapsed < STREAM_MAX_DURATION:
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

        await asyncio.sleep(STREAM_POLL_INTERVAL)
        elapsed += STREAM_POLL_INTERVAL

    yield f"data: {json.dumps({'error': 'Stream timeout', 'elapsed': elapsed})}\n\n"
