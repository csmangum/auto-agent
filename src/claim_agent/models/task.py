"""Pydantic models for the claim task system.

Tasks represent discrete, trackable units of work that agents or adjusters
create during claim processing. Examples: requesting documents, scheduling
inspections, contacting witnesses, gathering additional information.
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TaskType(str, Enum):
    """Classification of task."""

    GATHER_INFORMATION = "gather_information"
    CONTACT_WITNESS = "contact_witness"
    REQUEST_DOCUMENTS = "request_documents"
    SCHEDULE_INSPECTION = "schedule_inspection"
    FOLLOW_UP_CLAIMANT = "follow_up_claimant"
    REVIEW_DOCUMENTS = "review_documents"
    OBTAIN_POLICE_REPORT = "obtain_police_report"
    MEDICAL_RECORDS_REVIEW = "medical_records_review"
    APPRAISAL = "appraisal"
    SUBROGATION_FOLLOW_UP = "subrogation_follow_up"
    SIU_REFERRAL = "siu_referral"
    CONTACT_REPAIR_SHOP = "contact_repair_shop"
    VERIFY_COVERAGE = "verify_coverage"
    OTHER = "other"


class TaskStatus(str, Enum):
    """Lifecycle status of a task."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class TaskPriority(str, Enum):
    """Urgency level for a task."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class TaskCreateInput(BaseModel):
    """Input for creating a new task on a claim."""

    title: str = Field(..., min_length=1, max_length=500, description="Short description of the task")
    task_type: TaskType = Field(..., description="Category of the task")
    description: str = Field(default="", max_length=5000, description="Detailed description of what needs to be done")
    priority: TaskPriority = Field(default=TaskPriority.MEDIUM, description="Task priority")
    assigned_to: Optional[str] = Field(default=None, max_length=200, description="Person or team assigned (adjuster ID, crew name, etc.)")
    due_date: Optional[str] = Field(default=None, description="Target completion date (ISO 8601)")


class TaskUpdateInput(BaseModel):
    """Input for updating an existing task."""

    title: Optional[str] = Field(default=None, min_length=1, max_length=500)
    description: Optional[str] = Field(default=None, max_length=5000)
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assigned_to: Optional[str] = Field(default=None, max_length=200)
    due_date: Optional[str] = None
    resolution_notes: Optional[str] = Field(default=None, max_length=5000, description="Notes on how the task was resolved")


class ClaimTask(BaseModel):
    """Full task record as returned by the API."""

    id: int
    claim_id: str
    title: str
    task_type: TaskType
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.MEDIUM
    assigned_to: Optional[str] = None
    created_by: str = "workflow"
    due_date: Optional[str] = None
    resolution_notes: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
