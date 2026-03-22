"""Optional in-process scheduler for periodic UCSPA and diary jobs."""

from __future__ import annotations

import asyncio
import logging
import threading

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from claim_agent.compliance.ucspa import claims_with_deadlines_approaching
from claim_agent.config import get_settings
from claim_agent.db.repository import ClaimRepository
from claim_agent.diary.escalation import run_deadline_escalation
from claim_agent.notifications.webhook import dispatch_ucspa_deadline_approaching

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()


def _run_diary_escalation_job() -> None:
    """Run overdue-task notification and escalation sweep."""
    try:
        result = run_deadline_escalation()
        logger.info(
            "Scheduler diary escalation complete: notified=%d escalated=%d",
            result.get("notified_count", 0),
            result.get("escalated_count", 0),
        )
    except Exception:
        logger.exception("Scheduler diary escalation failed")


def _run_ucspa_deadline_job() -> None:
    """Run UCSPA deadline sweep and dispatch approaching-deadline webhooks."""
    settings = get_settings().scheduler
    claims = claims_with_deadlines_approaching(
        ClaimRepository(),
        days_ahead=settings.ucspa_days_ahead,
    )
    for claim in claims:
        try:
            dispatch_ucspa_deadline_approaching(
                claim["claim_id"],
                claim["deadline_type"],
                claim["due_date"],
                claim.get("loss_state"),
            )
        except Exception:
            logger.exception(
                "Scheduler UCSPA deadline dispatch failed: claim_id=%s deadline_type=%s",
                claim.get("claim_id"),
                claim.get("deadline_type"),
            )
    logger.info("Scheduler UCSPA deadline sweep complete: alerts=%d", len(claims))


def ensure_scheduler_running() -> None:
    """Start in-process scheduler when enabled. Safe to call multiple times."""
    global _scheduler

    config = get_settings().scheduler
    if not config.enabled:
        return

    with _scheduler_lock:
        if _scheduler is not None:
            return
        try:
            scheduler = BackgroundScheduler(timezone=config.timezone)
            scheduler.add_job(
                _run_diary_escalation_job,
                trigger=CronTrigger.from_crontab(
                    config.diary_escalate_cron,
                    timezone=config.timezone,
                ),
                id="diary_escalate",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            scheduler.add_job(
                _run_ucspa_deadline_job,
                trigger=CronTrigger.from_crontab(
                    config.ucspa_deadline_check_cron,
                    timezone=config.timezone,
                ),
                id="ucspa_deadlines",
                replace_existing=True,
                max_instances=1,
                coalesce=True,
            )
            scheduler.start()
            _scheduler = scheduler
            logger.info(
                "In-process scheduler enabled (diary=%s ucspa=%s timezone=%s)",
                config.diary_escalate_cron,
                config.ucspa_deadline_check_cron,
                config.timezone,
            )
        except Exception:
            logger.exception("Failed to start in-process scheduler")


async def stop_scheduler() -> None:
    """Stop in-process scheduler if running."""
    global _scheduler

    with _scheduler_lock:
        scheduler = _scheduler
        _scheduler = None

    if scheduler is not None:
        await asyncio.to_thread(scheduler.shutdown, wait=False)
