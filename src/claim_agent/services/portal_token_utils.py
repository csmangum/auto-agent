"""Shared helpers for portal magic-link token hashing and last-used inactivity checks."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any


def hash_portal_token(token: str) -> str:
    """SHA-256 hash of token for storage comparison."""
    return hashlib.sha256(token.encode()).hexdigest()


def portal_token_last_used_rejects(
    last_used: object | None,
    inactivity_cutoff: datetime,
    *,
    logger: logging.Logger,
    inactive_log: str | None,
    inactive_args: tuple[Any, ...] = (),
    token_id: object | None = None,
) -> bool:
    """Return True if verification must reject due to inactivity or bad ``last_used_at``.

    - If ``last_used`` is None, returns False (no inactivity evidence yet).
    - If parsed UTC datetime is strictly before ``inactivity_cutoff``, returns True.
    - If parsing fails, logs a warning and returns True (fail closed).
    """
    if last_used is None:
        return False
    try:
        last_used_dt = datetime.fromisoformat(str(last_used).replace("Z", "+00:00"))
        if last_used_dt.tzinfo is None:
            last_used_dt = last_used_dt.replace(tzinfo=timezone.utc)
        if last_used_dt < inactivity_cutoff:
            if inactive_log:
                logger.info(inactive_log, *inactive_args)
            return True
        return False
    except (ValueError, TypeError):
        logger.warning(
            "Unparseable last_used_at for portal token id=%s; rejecting",
            token_id,
        )
        return True
