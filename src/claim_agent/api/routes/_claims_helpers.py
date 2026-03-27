"""Shared helper functions and constants for claims routes."""

import asyncio
import json
import logging
from typing import Any, NoReturn

from fastapi import HTTPException
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.claim_access import adjuster_identity_scopes_assignee
from claim_agent.config import get_settings
from claim_agent.context import ClaimContext
from claim_agent.crews.main_crew import run_claim_workflow
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.constants import STATUS_FAILED, STATUS_NEEDS_REVIEW
from claim_agent.db.database import get_db_path
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimAlreadyProcessingError, InvalidClaimTransitionError
from claim_agent.models.document import DocumentType
from claim_agent.storage import get_storage_adapter
from claim_agent.storage.local import LocalStorageAdapter
from claim_agent.storage.s3 import S3StorageAdapter
from claim_agent.utils.sanitization import _is_safe_attachment_url

logger = logging.getLogger(__name__)

_CLAIM_ALREADY_PROCESSING_RETRY_AFTER = "30"

ALLOWED_DOCUMENT_EXTENSIONS = frozenset(
    {"pdf", "jpg", "jpeg", "png", "gif", "webp", "heic", "doc", "docx", "xls", "xlsx"}
)

VALID_DOCUMENT_TYPES = frozenset(dt.value for dt in DocumentType)

STREAM_POLL_INTERVAL = 1.0
STREAM_MAX_DURATION = 300

PRIORITY_VALUES = ("critical", "high", "medium", "low")

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
        headers={"Retry-After": _CLAIM_ALREADY_PROCESSING_RETRY_AFTER},
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


async def try_run_workflow_background(
    claim_id: str,
    claim_data_with_attachments: dict,
    actor_id: str,
    ctx: ClaimContext | None = None,
) -> asyncio.Task | None:
    """Run claim workflow in background if under concurrent limit. Returns None when at capacity."""
    max_tasks = get_settings().max_concurrent_background_tasks
    async with background_tasks_lock:
        if max_tasks > 0 and len(background_tasks) >= max_tasks:
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
            if not _is_safe_attachment_url(url):
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
