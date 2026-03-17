"""Shared utility functions for fraud detection modules."""

from datetime import date, datetime
from typing import Any


def _as_nonempty_str(raw: Any) -> str:
    """Coerce value to non-empty trimmed string, or empty string."""
    return raw.strip() if isinstance(raw, str) else ""


def _coerce_date(raw: Any) -> datetime | None:
    """Coerce value to datetime. Accepts datetime, date, or ISO date string."""
    if isinstance(raw, datetime):
        return raw
    if isinstance(raw, date):
        return datetime.combine(raw, datetime.min.time())
    if isinstance(raw, str):
        try:
            return datetime.strptime(raw.strip(), "%Y-%m-%d")
        except ValueError:
            return None
    return None
