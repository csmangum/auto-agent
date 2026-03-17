"""Task management API routes for claim tasks.

Provides endpoints for creating, listing, updating, and viewing tasks
that agents or adjusters create during claim processing.
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.context import ClaimContext
from claim_agent.db.audit_events import ACTOR_WORKFLOW
from claim_agent.db.database import get_db_path
from claim_agent.diary.recurrence import VALID_RECURRENCE_RULES
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


def _validate_due_date(v: Optional[str]) -> Optional[str]:
    """Validate due_date is YYYY-MM-DD or empty."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    try:
        datetime.fromisoformat(v.strip()).date()
    except (ValueError, TypeError):
        raise ValueError("due_date must be YYYY-MM-DD (ISO 8601)")
    return v.strip()


class CreateTaskBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=500, description="Short description of the task")
    task_type: str = Field(..., description="Task category")
    description: str = Field(default="", max_length=5000, description="Detailed description")
    priority: str = Field(default="medium", description="Task priority")
    assigned_to: Optional[str] = Field(default=None, max_length=200, description="Assignee")
    due_date: Optional[str] = Field(default=None, description="Target date (ISO 8601)")
    recurrence_rule: Optional[str] = Field(default=None, description="daily, interval_days, weekly")
    recurrence_interval: Optional[int] = Field(default=None, ge=1, description="For interval_days: every N days")

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, v: Optional[str]) -> Optional[str]:
        return _validate_due_date(v)

    @field_validator("recurrence_rule")
    @classmethod
    def validate_recurrence_rule(cls, v: Optional[str]) -> Optional[str]:
        if v is None or (isinstance(v, str) and v.strip() == ""):
            return None
        if v.strip() in VALID_RECURRENCE_RULES:
            return v.strip()
        raise ValueError(f"recurrence_rule must be one of: {', '.join(sorted(VALID_RECURRENCE_RULES))}")


class UpdateTaskBody(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[str] = None
    priority: Optional[str] = None
    assigned_to: Optional[str] = Field(default=None, max_length=200)
    due_date: Optional[str] = None
    resolution_notes: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("due_date")
    @classmethod
    def validate_due_date(cls, v: Optional[str]) -> Optional[str]:
        return _validate_due_date(v)


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
            recurrence_rule=body.recurrence_rule,
            recurrence_interval=body.recurrence_interval,
        )
    except ClaimNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

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


@router.get("/tasks/overdue")
def list_overdue_tasks(
    limit: int = Query(100, ge=1, le=500),
    auth: AuthContext = RequireAdjuster,
    ctx: ClaimContext = Depends(get_claim_context),
):
    """List overdue tasks (due_date passed, not completed/cancelled)."""
    tasks = ctx.repo.list_overdue_tasks(limit=limit)
    return {"tasks": tasks, "total": len(tasks)}


@router.get("/diary/compliance-templates")
def get_compliance_templates(
    state: Optional[str] = Query(None, description="Loss state for state-specific deadlines"),
    auth: AuthContext = RequireAdjuster,
):
    """Get state-specific compliance deadline templates for diary creation."""
    from claim_agent.diary.templates import get_compliance_deadline_templates

    templates = get_compliance_deadline_templates(state)
    return {
        "templates": [
            {
                "deadline_type": t.deadline_type,
                "title": t.title,
                "task_type": t.task_type,
                "description": t.description,
                "days": t.days,
                "state": t.state,
            }
            for t in templates
        ],
    }


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
        msg = str(e)
        if "Task not found" in msg:
            raise HTTPException(status_code=404, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e
    return updated
