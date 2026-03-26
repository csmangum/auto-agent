"""Task tools for agent-driven task creation and management.

Agents and crews can create tasks for future completion during claim
processing. Common use cases: requesting documents, scheduling inspections,
contacting witnesses, gathering additional information.
"""

import json
import logging

from crewai.tools import tool

from claim_agent.db.document_repository import DocumentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.tools.document_logic import DOCUMENT_TYPE_OPTIONS
from claim_agent.diary.recurrence import VALID_RECURRENCE_RULES
from claim_agent.exceptions import ClaimNotFoundError, DomainValidationError
from claim_agent.models.task import TaskPriority, TaskStatus, TaskType
from claim_agent.utils.sanitization import (
    sanitize_actor_id,
    sanitize_task_description,
    sanitize_task_title,
    sanitize_resolution_notes,
)

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
    document_type: str = "",
    requested_from: str = "",
    recurrence_rule: str = "",
    recurrence_interval: str = "",
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
    - Recurring: check repair status every 3 days (recurrence_rule=interval_days, recurrence_interval=3)

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
        document_type: When task_type is request_documents or obtain_police_report,
            the type of document requested (police_report, estimate, medical_records, etc.).
        requested_from: When creating a document request, the party to request from.
        recurrence_rule: For recurring tasks: daily, interval_days, weekly. Leave empty for one-time.
        recurrence_interval: For interval_days: e.g. 3 for every 3 days. For daily/weekly: 1.

    Returns:
        JSON with success (bool), task_id (int), and message.
    """
    claim_id = str(claim_id).strip()
    title = sanitize_task_title(title)
    task_type = str(task_type).strip()
    description = sanitize_task_description(description)
    priority = str(priority).strip() or "medium"
    assigned_to_val = str(assigned_to).strip() or None
    created_by = sanitize_actor_id(created_by) or "workflow"
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

    doc_type = str(document_type).strip() or None
    requested_from_val = str(requested_from).strip() or None
    recur_rule = str(recurrence_rule).strip() or None
    recur_interval_val: int | None = None
    if str(recurrence_interval).strip():
        try:
            recur_interval_val = int(recurrence_interval)
            if recur_interval_val < 1:
                raise ValueError("must be >= 1")
        except ValueError:
            return json.dumps({
                "success": False,
                "task_id": None,
                "message": f"Invalid recurrence_interval: must be a positive integer, got '{recurrence_interval}'",
            })
    if recur_interval_val is not None and recur_rule is None:
        return json.dumps({
            "success": False,
            "task_id": None,
            "message": "recurrence_interval requires recurrence_rule to be set",
        })
    if recur_rule and recur_rule not in VALID_RECURRENCE_RULES:
        return json.dumps({
            "success": False,
            "task_id": None,
            "message": f"Invalid recurrence_rule: {recur_rule}. Use: daily, interval_days, weekly.",
        })
    if recur_rule == "interval_days" and recur_interval_val is None:
        return json.dumps({
            "success": False,
            "task_id": None,
            "message": "recurrence_interval is required when recurrence_rule is 'interval_days'",
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
            document_type=doc_type,
            requested_from=requested_from_val,
            recurrence_rule=recur_rule,
            recurrence_interval=recur_interval_val,
        )
        return json.dumps({
            "success": True,
            "task_id": task_id,
            "message": f"Task created: {title}",
        })
    except ClaimNotFoundError:
        return json.dumps({"success": False, "task_id": None, "message": f"Claim not found: {claim_id}"})
    except DomainValidationError as e:
        return json.dumps({"success": False, "task_id": None, "message": str(e)})
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
    resolution_val = sanitize_resolution_notes(resolution_notes) or None
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
    except DomainValidationError as e:
        return json.dumps({"success": False, "message": str(e)})
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
                "recurrence_rule": t.get("recurrence_rule"),
                "recurrence_interval": t.get("recurrence_interval"),
                "escalation_level": t.get("escalation_level", 0),
                "auto_created_from": t.get("auto_created_from"),
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


@tool("Create Document Request")
def create_document_request(
    claim_id: str,
    document_type: str,
    requested_from: str = "",
) -> str:
    """Create a document request to track requested -> received documents.

    Use when you need to formally request a document (police_report, estimate,
    rental_receipt, rental_agreement, medical_record, etc.) and track when it is received.

    Args:
        claim_id: The claim ID.
        document_type: Type of document (police_report, estimate, rental_receipt,
            rental_agreement, medical_record, etc.).
        requested_from: Party to request from (claimant, police, provider, repair_shop).

    Returns:
        JSON with success, request_id, request.
    """
    claim_id = str(claim_id).strip()
    document_type = str(document_type).strip()
    requested_from_val = str(requested_from).strip() or None
    if not claim_id:
        return json.dumps({"success": False, "request_id": None, "error": "claim_id is required"})
    if not document_type:
        return json.dumps({"success": False, "request_id": None, "error": "document_type is required"})
    if document_type not in DOCUMENT_TYPE_OPTIONS:
        return json.dumps({
            "success": False,
            "request_id": None,
            "error": (
                f"Unknown document_type {document_type!r}. "
                f"Valid types: {', '.join(sorted(DOCUMENT_TYPE_OPTIONS))}"
            ),
        })
    try:
        doc_repo = DocumentRepository()
        req_id = doc_repo.create_document_request(
            claim_id, document_type, requested_from=requested_from_val
        )
        req = doc_repo.get_document_request(req_id)
        return json.dumps({"success": True, "request_id": req_id, "request": req})
    except ClaimNotFoundError:
        return json.dumps({"success": False, "request_id": None, "error": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error creating document request for claim %s", claim_id)
        return json.dumps({"success": False, "request_id": None, "error": "An unexpected error occurred"})


@tool("Get Document Requests")
def get_document_requests(claim_id: str, status: str = "") -> str:
    """Retrieve document requests for a claim.

    Use to see what documents have been requested and their status (requested, received, etc.).

    Args:
        claim_id: The claim ID.
        status: Optional filter by status (requested, received, partial, overdue).

    Returns:
        JSON with requests (list), total, error.
    """
    claim_id = str(claim_id).strip()
    status_val = str(status).strip() or None
    if not claim_id:
        return json.dumps({"requests": None, "total": 0, "error": "claim_id is required"})
    try:
        doc_repo = DocumentRepository()
        requests, total = doc_repo.list_document_requests(claim_id, status=status_val)
        return json.dumps({"requests": requests, "total": total, "error": None})
    except Exception:
        logger.exception("Unexpected error retrieving document requests for claim %s", claim_id)
        return json.dumps({"requests": None, "total": 0, "error": "An unexpected error occurred"})
