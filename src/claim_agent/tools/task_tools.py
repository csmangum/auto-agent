"""Task tools for agent-driven task creation and management.

Agents and crews can create tasks for future completion during claim
processing. Common use cases: requesting documents, scheduling inspections,
contacting witnesses, gathering additional information.
"""

import json
import logging

from crewai.tools import tool

from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.task import TaskPriority, TaskStatus, TaskType

logger = logging.getLogger(__name__)

VALID_TASK_TYPES = {t.value for t in TaskType}
VALID_PRIORITIES = {p.value for p in TaskPriority}
VALID_STATUSES = {s.value for s in TaskStatus}


@tool("Create Claim Task")
def create_claim_task(
    claim_id: str,
    title: str,
    task_type: str,
    description: str = "",
    priority: str = "medium",
    assigned_to: str = "",
    created_by: str = "workflow",
    due_date: str = "",
) -> str:
    """Create a task on a claim for future completion.

    Use this tool to schedule follow-up actions that need to happen later
    during claim processing. Examples:
    - Request documents from the claimant
    - Schedule a vehicle inspection
    - Contact a witness for a statement
    - Follow up on medical records
    - Refer to SIU for investigation
    - Verify policy coverage details

    Args:
        claim_id: The claim ID (e.g., CLM-XXXXXXXX).
        title: Short description of what needs to be done.
        task_type: Category. One of: gather_information, contact_witness,
            request_documents, schedule_inspection, follow_up_claimant,
            review_documents, obtain_police_report, medical_records_review,
            appraisal, subrogation_follow_up, siu_referral, contact_repair_shop,
            verify_coverage, other.
        description: Detailed description of what needs to be done and why.
        priority: Task urgency. One of: low, medium, high, urgent.
        assigned_to: Person or team assigned (e.g., adjuster ID, crew name).
            Leave empty to leave unassigned.
        created_by: Identifier for who created the task (crew name, agent, or 'workflow').
        due_date: Optional target completion date in ISO 8601 format (YYYY-MM-DD).
            Leave empty for no due date.

    Returns:
        JSON with success (bool), task_id (int), and message.
    """
    claim_id = str(claim_id).strip()
    title = str(title).strip()
    task_type = str(task_type).strip()
    description = str(description).strip()
    priority = str(priority).strip() or "medium"
    assigned_to_val = str(assigned_to).strip() or None
    created_by = str(created_by).strip() or "workflow"
    due_date_val = str(due_date).strip() or None

    if not claim_id:
        return json.dumps({"success": False, "task_id": None, "message": "claim_id is required"})
    if not title:
        return json.dumps({"success": False, "task_id": None, "message": "title is required"})
    if task_type not in VALID_TASK_TYPES:
        return json.dumps({
            "success": False,
            "task_id": None,
            "message": f"Invalid task_type: {task_type}. Must be one of: {', '.join(sorted(VALID_TASK_TYPES))}",
        })
    if priority not in VALID_PRIORITIES:
        return json.dumps({
            "success": False,
            "task_id": None,
            "message": f"Invalid priority: {priority}. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}",
        })

    try:
        task_id = ClaimRepository().create_task(
            claim_id,
            title,
            task_type,
            description=description,
            priority=priority,
            assigned_to=assigned_to_val,
            created_by=created_by,
            due_date=due_date_val,
        )
        return json.dumps({
            "success": True,
            "task_id": task_id,
            "message": f"Task created: {title}",
        })
    except ClaimNotFoundError:
        return json.dumps({"success": False, "task_id": None, "message": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error creating task for claim %s", claim_id)
        return json.dumps({"success": False, "task_id": None, "message": "An unexpected error occurred while creating the task"})


@tool("Update Claim Task")
def update_claim_task(
    task_id: int,
    status: str = "",
    resolution_notes: str = "",
    assigned_to: str = "",
    priority: str = "",
) -> str:
    """Update a task's status, assignment, priority, or add resolution notes.

    Use this when a task has been completed, is in progress, blocked, or
    needs reassignment.

    Args:
        task_id: The task ID (integer).
        status: New status. One of: pending, in_progress, completed, cancelled, blocked.
            Leave empty to keep current status.
        resolution_notes: Notes on how the task was resolved or what was found.
            Leave empty to keep current notes.
        assigned_to: New assignee. Leave empty to keep current assignment.
        priority: New priority. One of: low, medium, high, urgent.
            Leave empty to keep current priority.

    Returns:
        JSON with success (bool) and message.
    """
    status_val = str(status).strip() or None
    resolution_val = str(resolution_notes).strip() or None
    assigned_val = str(assigned_to).strip() or None
    priority_val = str(priority).strip() or None

    if status_val and status_val not in VALID_STATUSES:
        return json.dumps({
            "success": False,
            "message": f"Invalid status: {status_val}. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        })
    if priority_val and priority_val not in VALID_PRIORITIES:
        return json.dumps({
            "success": False,
            "message": f"Invalid priority: {priority_val}. Must be one of: {', '.join(sorted(VALID_PRIORITIES))}",
        })

    try:
        updated = ClaimRepository().update_task(
            int(task_id),
            status=status_val,
            resolution_notes=resolution_val,
            assigned_to=assigned_val,
            priority=priority_val,
        )
        return json.dumps({
            "success": True,
            "message": f"Task {task_id} updated (status={updated.get('status')})",
        })
    except ValueError as e:
        return json.dumps({"success": False, "message": str(e)})
    except Exception:
        logger.exception("Unexpected error updating task %s", task_id)
        return json.dumps({"success": False, "message": "An unexpected error occurred while updating the task"})


@tool("Get Claim Tasks")
def get_claim_tasks(claim_id: str) -> str:
    """Retrieve all tasks for a claim.

    Use this to see what tasks have been created, their status, and what
    work remains. Useful for reviewing pending work before making decisions.

    Args:
        claim_id: The claim ID (e.g., CLM-XXXXXXXX).

    Returns:
        JSON with tasks (list) and error (null on success, string on failure).
    """
    claim_id = str(claim_id).strip()
    if not claim_id:
        return json.dumps({"tasks": None, "error": "claim_id is required"})

    try:
        tasks, total = ClaimRepository().get_tasks_for_claim(claim_id)
        out = [
            {
                "id": t["id"],
                "title": t["title"],
                "task_type": t["task_type"],
                "status": t["status"],
                "priority": t["priority"],
                "assigned_to": t.get("assigned_to"),
                "created_by": t.get("created_by"),
                "due_date": t.get("due_date"),
                "description": t.get("description", ""),
                "resolution_notes": t.get("resolution_notes"),
                "created_at": t.get("created_at"),
            }
            for t in tasks
        ]
        return json.dumps({"tasks": out, "total": total, "error": None})
    except ClaimNotFoundError:
        return json.dumps({"tasks": None, "error": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error retrieving tasks for claim %s", claim_id)
        return json.dumps({"tasks": None, "error": "An unexpected error occurred while retrieving tasks"})
