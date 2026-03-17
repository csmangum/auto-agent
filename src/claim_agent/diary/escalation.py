"""Deadline escalation: overdue -> notify -> auto-escalate to supervisor."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from claim_agent.config import get_settings
from claim_agent.db.repository import ClaimRepository
from claim_agent.notifications.webhook import dispatch_webhook

logger = logging.getLogger(__name__)


def run_deadline_escalation(*, db_path: str | None = None) -> dict[str, int]:
    """Process overdue tasks: notify level 0, escalate level 1 after threshold.

    Returns:
        Dict with notified_count, escalated_count.
    """
    repo = ClaimRepository(db_path=db_path)
    config = get_settings().diary
    notified_count = 0
    escalated_count = 0

    # Level 0: overdue, not yet notified -> send webhook, mark notified
    overdue_not_notified = repo.list_overdue_tasks(max_escalation_level=0)
    for task in overdue_not_notified:
        try:
            _dispatch_task_overdue(task)
            repo.mark_task_overdue_notified(task["id"])
            notified_count += 1
        except Exception as e:
            logger.warning("task_overdue_notify_failed task_id=%s: %s", task["id"], e)

    # Level 1: notified, check if past escalation threshold -> escalate to supervisor
    overdue_notified = repo.list_overdue_tasks(max_escalation_level=1)
    for task in overdue_notified:
        if _should_escalate_to_supervisor(task, config.escalation_hours_before_supervisor):
            try:
                _dispatch_task_supervisor_escalated(task)
                repo.mark_task_supervisor_escalated(task["id"])
                escalated_count += 1
            except Exception as e:
                logger.warning("task_supervisor_escalate_failed task_id=%s: %s", task["id"], e)

    return {"notified_count": notified_count, "escalated_count": escalated_count}


def _should_escalate_to_supervisor(task: dict, hours_threshold: int) -> bool:
    """True if task was notified at least hours_threshold ago."""
    notified_at = task.get("escalation_notified_at")
    if not notified_at:
        return False
    try:
        dt = datetime.fromisoformat(notified_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - dt).total_seconds()
        return elapsed >= hours_threshold * 3600
    except (ValueError, TypeError):
        return False


def _dispatch_task_overdue(task: dict) -> None:
    """Dispatch task.overdue webhook."""
    payload = {
        "task_id": task["id"],
        "claim_id": task["claim_id"],
        "title": task["title"],
        "task_type": task.get("task_type"),
        "due_date": task.get("due_date"),
        "assigned_to": task.get("assigned_to"),
        "priority": task.get("priority"),
    }
    dispatch_webhook("task.overdue", payload)


def _dispatch_task_supervisor_escalated(task: dict) -> None:
    """Dispatch task.supervisor_escalated webhook."""
    payload = {
        "task_id": task["id"],
        "claim_id": task["claim_id"],
        "title": task["title"],
        "task_type": task.get("task_type"),
        "due_date": task.get("due_date"),
        "assigned_to": task.get("assigned_to"),
        "escalation_notified_at": task.get("escalation_notified_at"),
    }
    dispatch_webhook("task.supervisor_escalated", payload)
