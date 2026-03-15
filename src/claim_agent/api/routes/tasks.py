"""Task management API routes for claim tasks.

Provides endpoints for creating, listing, updating, and viewing tasks
that agents or adjusters create during claim processing.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.context import ClaimContext
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.database import get_db_path
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.task import TaskPriority, TaskStatus, TaskType

logger = logging.getLogger(__name__)


def get_claim_context() -> ClaimContext:
    return ClaimContext.from_defaults(db_path=get_db_path())


router = APIRouter(tags=["tasks"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin")

VALID_TASK_STATUSES = {s.value for s in TaskStatus}
VALID_TASK_TYPES = {t.value for t in TaskType}
VALID_TASK_PRIORITIES = {p.value for p in TaskPriority}


class CreateTaskBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Short description of the task")
    task_type: str = Field(..., description="Task category")
    description: str = Field(default="", max_length=5000, description="Detailed description")
    priority: str = Field(default="medium", description="Task priority")
    assigned_to: Optional[str] = Field(default=None, max_length=200, description="Assignee")
    due_date: Optional[str] = Field(default=None, description="Target date (ISO 8601)")


class UpdateTaskBody(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = Field(default=None, max_length=200)
    due_date: Optional[str] = None
    resolution_notes: Optional[str] = Field(default=None, max_length=5000)


@router.post("/claims/{claim_id}/tasks")
def create_task(
    claim_id: str,
    body: CreateTaskBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Create a new task for a claim."""
    if body.task_type not in VALID_TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type: {body.task_type}. Must be one of: {', '.join(sorted(VALID_TASK_TYPES))}",
        )
    if body.priority not in VALID_TASK_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority: {body.priority}. Must be one of: {', '.join(sorted(VALID_TASK_PRIORITIES))}",
        )
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        task_id = ctx.repo.create_task(
            claim_id,
            body.title,
            body.task_type,
            description=body.description,
            priority=body.priority,
            assigned_to=body.assigned_to,
            created_by=actor_id,
            due_date=body.due_date,
        )
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    task = ctx.repo.get_task(task_id)
    return task


@router.get("/claims/{claim_id}/tasks")
def list_claim_tasks(
    claim_id: str,
    status: Optional[str] = Query(None, description="Filter by task status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List tasks for a specific claim."""
    if ctx.repo.get_claim(claim_id) is None:
        raise HTTPException(status_code=404, detail=f"Claim not found: {claim_id}")
    if status is not None and status not in VALID_TASK_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status filter: {status}. Must be one of: {', '.join(sorted(VALID_TASK_STATUSES))}",
        )
    tasks, total = ctx.repo.get_tasks_for_claim(claim_id, status=status, limit=limit, offset=offset)
    return {"claim_id": claim_id, "tasks": tasks, "total": total, "limit": limit, "offset": offset}


@router.get("/tasks")
def list_all_tasks(
    status: Optional[str] = Query(None, description="Filter by task status"),
    task_type: Optional[str] = Query(None, description="Filter by task type"),
    assigned_to: Optional[str] = Query(None, description="Filter by assignee"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List tasks across all claims with optional filters."""
    if status is not None and status not in VALID_TASK_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
    if task_type is not None and task_type not in VALID_TASK_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid task_type: {task_type}")
    tasks, total = ctx.repo.list_all_tasks(
        status=status, task_type=task_type, assigned_to=assigned_to,
        limit=limit, offset=offset,
    )
    return {"tasks": tasks, "total": total, "limit": limit, "offset": offset}


@router.get("/tasks/stats")
def get_task_stats(
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get aggregate task statistics."""
    return ctx.repo.get_task_stats()


@router.get("/tasks/{task_id}")
def get_task(
    task_id: int,
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Get a single task by ID."""
    task = ctx.repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return task


@router.patch("/tasks/{task_id}")
def update_task(
    task_id: int,
    body: UpdateTaskBody = Body(...),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """Update a task (status, priority, assignment, etc.)."""
    if body.status is not None and body.status not in VALID_TASK_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status: {body.status}. Must be one of: {', '.join(sorted(VALID_TASK_STATUSES))}",
        )
    if body.priority is not None and body.priority not in VALID_TASK_PRIORITIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid priority: {body.priority}. Must be one of: {', '.join(sorted(VALID_TASK_PRIORITIES))}",
        )
    actor_id = auth.identity if auth.identity != "anonymous" else ACTOR_WORKFLOW
    try:
        updated = ctx.repo.update_task(
            task_id,
            title=body.title,
            description=body.description,
            status=body.status,
            priority=body.priority,
            assigned_to=body.assigned_to,
            due_date=body.due_date,
            resolution_notes=body.resolution_notes,
            actor_id=actor_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return updated
