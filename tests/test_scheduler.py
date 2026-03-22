"""Tests for optional in-process scheduler."""

from types import SimpleNamespace
from unittest.mock import patch

import claim_agent.scheduler as scheduler


def _scheduler_settings(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=enabled,
        timezone="UTC",
        diary_escalate_cron="0 * * * *",
        ucspa_deadline_check_cron="0 9 * * *",
        ucspa_days_ahead=3,
    )


def test_ensure_scheduler_running_noop_when_disabled():
    scheduler._scheduler = None
    with patch("claim_agent.scheduler.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(scheduler=_scheduler_settings(enabled=False))
        with patch("claim_agent.scheduler.BackgroundScheduler") as mock_background:
            scheduler.ensure_scheduler_running()
            mock_background.assert_not_called()


def test_ensure_scheduler_running_starts_jobs_when_enabled():
    scheduler._scheduler = None
    fake_scheduler = SimpleNamespace(
        add_job=lambda *args, **kwargs: None,
        start=lambda: None,
    )
    with patch("claim_agent.scheduler.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(scheduler=_scheduler_settings(enabled=True))
        with patch("claim_agent.scheduler.BackgroundScheduler", return_value=fake_scheduler):
            scheduler.ensure_scheduler_running()

    assert scheduler._scheduler is fake_scheduler
    scheduler._scheduler = None


def test_run_ucspa_deadline_job_dispatches_webhooks():
    with patch("claim_agent.scheduler.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(scheduler=_scheduler_settings(enabled=True))
        with patch("claim_agent.scheduler.claims_with_deadlines_approaching") as mock_claims:
            mock_claims.return_value = [
                {
                    "claim_id": "CLM-TEST001",
                    "deadline_type": "acknowledgment",
                    "due_date": "2026-03-23",
                    "loss_state": "California",
                }
            ]
            with patch("claim_agent.scheduler.dispatch_ucspa_deadline_approaching") as mock_dispatch:
                scheduler._run_ucspa_deadline_job()
                mock_dispatch.assert_called_once_with(
                    "CLM-TEST001",
                    "acknowledgment",
                    "2026-03-23",
                    "California",
                )
