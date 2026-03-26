"""Tests for optional in-process scheduler."""

import logging
from types import SimpleNamespace
from unittest.mock import patch

import claim_agent.scheduler as scheduler


def setup_function() -> None:
    scheduler._scheduler = None


def teardown_function() -> None:
    scheduler._scheduler = None


def _scheduler_settings(enabled: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        enabled=enabled,
        timezone="UTC",
        diary_escalate_cron="0 * * * *",
        ucspa_deadline_check_cron="0 9 * * *",
        erp_poll_cron="*/15 * * * *",
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
    add_job_calls: list[dict] = []

    def _add_job(*args, **kwargs):
        add_job_calls.append({"args": args, "kwargs": kwargs})

    fake_scheduler = SimpleNamespace(add_job=_add_job, start=lambda: None)
    with patch("claim_agent.scheduler.get_settings") as mock_get_settings:
        mock_get_settings.return_value = SimpleNamespace(scheduler=_scheduler_settings(enabled=True))
        with patch("claim_agent.scheduler.BackgroundScheduler", return_value=fake_scheduler):
            scheduler.ensure_scheduler_running()

    assert scheduler._scheduler is fake_scheduler
    assert len(add_job_calls) == 3
    job_ids = {call["kwargs"]["id"] for call in add_job_calls}
    assert job_ids == {"diary_escalate", "ucspa_deadlines", "erp_poll"}
    funcs = {call["args"][0] for call in add_job_calls}
    assert funcs == {
        scheduler._run_diary_escalation_job,
        scheduler._run_ucspa_deadline_job,
        scheduler._run_erp_poll_job,
    }
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


def test_api_server_does_not_auto_start_scheduler():
    """API server module must not expose ensure_scheduler_running in its namespace."""
    import claim_agent.api.server as server_mod

    # ensure_scheduler_running must not have been imported into server.py's namespace
    assert not hasattr(server_mod, "ensure_scheduler_running"), (
        "server.py must not import ensure_scheduler_running; "
        "the API server no longer auto-starts the scheduler."
    )


def test_api_server_warns_when_scheduler_enabled(caplog):
    """API server emits a warning when SCHEDULER_ENABLED=true is detected."""
    from claim_agent.api.server import _warn_if_scheduler_enabled_on_api

    # Patch SchedulerConfig (the class) so that calling SchedulerConfig() returns fake_cfg.
    fake_cfg = SimpleNamespace(enabled=True)
    with patch("claim_agent.api.server.SchedulerConfig", return_value=fake_cfg):
        with caplog.at_level(logging.WARNING, logger="claim_agent.api.server"):
            _warn_if_scheduler_enabled_on_api()

    assert any("run-scheduler" in r.message for r in caplog.records), (
        "Expected a warning mentioning 'claim-agent run-scheduler'"
    )


def test_api_server_no_warning_when_scheduler_disabled(caplog):
    """API server emits no warning when SCHEDULER_ENABLED=false (the default)."""
    from claim_agent.api.server import _warn_if_scheduler_enabled_on_api

    # Patch SchedulerConfig (the class) so that calling SchedulerConfig() returns fake_cfg.
    fake_cfg = SimpleNamespace(enabled=False)
    with patch("claim_agent.api.server.SchedulerConfig", return_value=fake_cfg):
        with caplog.at_level(logging.WARNING, logger="claim_agent.api.server"):
            _warn_if_scheduler_enabled_on_api()

    assert not caplog.records, "Expected no warnings when scheduler is disabled"
