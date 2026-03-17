"""Auto-create diary entries at claim status transitions."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from claim_agent.db.repository import ClaimRepository
from claim_agent.diary.templates import get_status_transition_templates
from claim_agent.events import ClaimEvent

logger = logging.getLogger(__name__)

_diary_listener_registered = False


def _on_claim_status_change(event: ClaimEvent) -> None:
    """Create diary entries for status transitions."""
    templates = get_status_transition_templates(
        _get_previous_status(event.claim_id) or "pending",
        event.status,
    )
    if not templates:
        return

    try:
        repo = ClaimRepository()
        claim = repo.get_claim(event.claim_id)
        if not claim:
            return

        base_date = date.today()
        for t in templates:
            due_date = (base_date + timedelta(days=t.due_days)).isoformat()
            try:
                repo.create_task(
                    event.claim_id,
                    t.title,
                    t.task_type,
                    description=t.description,
                    priority="medium",
                    created_by="diary_system",
                    due_date=due_date,
                    recurrence_rule=t.recurrence_rule,
                    recurrence_interval=t.recurrence_interval,
                    auto_created_from=f"status_transition:{t.from_status}->{t.to_status}",
                )
                logger.info(
                    "diary_auto_created claim_id=%s title=%s due=%s",
                    event.claim_id,
                    t.title,
                    due_date,
                )
            except Exception as e:
                logger.warning(
                    "diary_auto_create_failed claim_id=%s title=%s: %s",
                    event.claim_id,
                    t.title,
                    e,
                )
    except Exception as e:
        logger.warning("diary_auto_create_listener_error claim_id=%s: %s", event.claim_id, e)


def _get_previous_status(claim_id: str) -> str | None:
    """Get the previous status from audit log (last status_change before current)."""
    from claim_agent.db.audit_events import AUDIT_EVENT_STATUS_CHANGE
    from claim_agent.db.database import get_connection, get_db_path

    with get_connection(get_db_path()) as conn:
        row = conn.execute(
            """
            SELECT old_status FROM claim_audit_log
            WHERE claim_id = ? AND action = ?
            ORDER BY id DESC LIMIT 1
            """,
            (claim_id, AUDIT_EVENT_STATUS_CHANGE),
        ).fetchone()
    return row["old_status"] if row else None


def ensure_diary_listener_registered() -> None:
    """Register the diary auto-create listener (idempotent)."""
    global _diary_listener_registered
    if _diary_listener_registered:
        return

    from claim_agent.config import get_settings

    if not get_settings().diary.auto_create_on_status_change:
        return

    from claim_agent.events import register_claim_event_listener

    register_claim_event_listener(_on_claim_status_change)
    _diary_listener_registered = True
