"""Calendar/Diary system for claim tasks.

Provides:
- Recurrence rules for tasks (e.g. check repair status every 3 days)
- Deadline escalation (overdue -> notify -> auto-escalate to supervisor)
- Auto-create diary entries at key status transitions
- State-specific compliance deadline templates

Note: Recurrence (recurrence_rule, recurrence_interval, parent_task_id) is stored
on tasks but not yet executed by a follow-up instance scheduler. This package
provides overdue/supervisor escalation jobs only; recurring task instance
generation should be run by a separate cron or scheduler job.
"""

from claim_agent.diary.templates import (
    get_compliance_deadline_templates,
    get_status_transition_templates,
)
from claim_agent.diary.recurrence import (
    compute_next_due_date,
    RECURRENCE_DAILY,
    RECURRENCE_INTERVAL_DAYS,
    RECURRENCE_WEEKLY,
)

__all__ = [
    "get_compliance_deadline_templates",
    "get_status_transition_templates",
    "compute_next_due_date",
    "RECURRENCE_DAILY",
    "RECURRENCE_INTERVAL_DAYS",
    "RECURRENCE_WEEKLY",
]
