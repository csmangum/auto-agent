"""Recurrence rules for claim tasks.

Supports: daily, interval_days (e.g. every 3 days), weekly.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

RECURRENCE_DAILY = "daily"
RECURRENCE_INTERVAL_DAYS = "interval_days"
RECURRENCE_WEEKLY = "weekly"

VALID_RECURRENCE_RULES = frozenset({RECURRENCE_DAILY, RECURRENCE_INTERVAL_DAYS, RECURRENCE_WEEKLY})


def compute_next_due_date(
    from_date: date | datetime | str,
    recurrence_rule: str,
    recurrence_interval: int = 1,
) -> Optional[date]:
    """Compute the next due date for a recurring task.

    Args:
        from_date: Reference date (e.g. last due_date or today).
        recurrence_rule: One of daily, interval_days, weekly.
        recurrence_interval: For interval_days: every N days. For daily/weekly: 1.

    Returns:
        Next due date, or None if rule invalid.
    """
    if isinstance(from_date, str):
        try:
            from_date = datetime.fromisoformat(from_date.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            from_date = date.today()
    elif isinstance(from_date, datetime):
        from_date = from_date.date()

    interval = max(1, recurrence_interval)

    if recurrence_rule == RECURRENCE_DAILY:
        return from_date + timedelta(days=interval)
    if recurrence_rule == RECURRENCE_INTERVAL_DAYS:
        return from_date + timedelta(days=interval)
    if recurrence_rule == RECURRENCE_WEEKLY:
        return from_date + timedelta(weeks=interval)
    return None
