"""Tests for diary system: recurrence, templates, escalation."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from claim_agent.db.database import get_connection
from claim_agent.db.repository import ClaimRepository
from claim_agent.diary.escalation import run_deadline_escalation
from claim_agent.diary.recurrence import (
    RECURRENCE_DAILY,
    RECURRENCE_INTERVAL_DAYS,
    RECURRENCE_WEEKLY,
    compute_next_due_date,
)
from claim_agent.diary.templates import (
    get_compliance_deadline_templates,
    get_status_transition_templates,
)


class TestRecurrence:
    def test_compute_next_daily(self):
        base = date(2026, 3, 15)
        next_date = compute_next_due_date(base, RECURRENCE_DAILY, 1)
        assert next_date == date(2026, 3, 16)

    def test_compute_next_interval_days(self):
        base = date(2026, 3, 15)
        next_date = compute_next_due_date(base, RECURRENCE_INTERVAL_DAYS, 3)
        assert next_date == date(2026, 3, 18)

    def test_compute_next_weekly(self):
        base = date(2026, 3, 15)
        next_date = compute_next_due_date(base, RECURRENCE_WEEKLY, 1)
        assert next_date == date(2026, 3, 22)

    def test_compute_next_from_string(self):
        next_date = compute_next_due_date("2026-03-15", RECURRENCE_INTERVAL_DAYS, 5)
        assert next_date == date(2026, 3, 20)

    def test_compute_next_invalid_rule_returns_none(self):
        assert compute_next_due_date(date(2026, 3, 15), "invalid", 1) is None


class TestComplianceTemplates:
    def test_get_templates_with_state(self):
        templates = get_compliance_deadline_templates("California")
        assert len(templates) >= 3
        types = {t.deadline_type for t in templates}
        assert "acknowledgment" in types
        assert "investigation" in types
        assert "prompt_payment" in types

    def test_get_templates_without_state(self):
        templates = get_compliance_deadline_templates(None)
        assert len(templates) >= 3


class TestStatusTransitionTemplates:
    def test_get_templates_for_transition(self):
        templates = get_status_transition_templates("pending", "processing")
        assert len(templates) >= 1
        assert templates[0].title == "Follow up on claim processing"
        assert templates[0].due_days == 3

    def test_get_templates_no_match(self):
        templates = get_status_transition_templates("closed", "archived")
        assert len(templates) == 0


class TestCreateTaskWithRecurrence:
    def test_create_task_with_recurrence(self, seeded_temp_db):
        repo = ClaimRepository()
        task_id = repo.create_task(
            "CLM-TEST001",
            "Check repair status",
            "contact_repair_shop",
            recurrence_rule="interval_days",
            recurrence_interval=3,
            due_date="2026-03-20",
        )
        task = repo.get_task(task_id)
        assert task["recurrence_rule"] == "interval_days"
        assert task["recurrence_interval"] == 3


class TestListOverdueTasks:
    def test_list_overdue_empty(self, temp_db):
        repo = ClaimRepository(db_path=temp_db)
        overdue = repo.list_overdue_tasks()
        assert overdue == []

    def test_list_overdue_includes_past_due(self, seeded_temp_db):
        repo = ClaimRepository()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task_id = repo.create_task(
            "CLM-TEST001",
            "Overdue task",
            "other",
            due_date=yesterday,
        )
        overdue = repo.list_overdue_tasks()
        assert len(overdue) == 1
        assert overdue[0]["id"] == task_id


class TestEscalation:
    def test_run_escalation_empty(self, temp_db):
        """Empty DB yields no notifications or escalations."""
        result = run_deadline_escalation(db_path=temp_db)
        assert result["notified_count"] == 0
        assert result["escalated_count"] == 0

    def test_run_escalation_notifies_overdue_task(self, seeded_temp_db):
        """Overdue task at level 0 gets notified and marked escalation_level=1."""
        repo = ClaimRepository()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task_id = repo.create_task(
            "CLM-TEST001",
            "Overdue notify test",
            "other",
            due_date=yesterday,
        )

        with patch("claim_agent.diary.escalation.dispatch_webhook") as mock_webhook:
            result = run_deadline_escalation()

        assert result["notified_count"] >= 1
        assert result["escalated_count"] == 0
        task = repo.get_task(task_id)
        assert task["escalation_level"] == 1
        assert task["escalation_notified_at"] is not None
        mock_webhook.assert_called_with("task.overdue", mock_webhook.call_args[0][1])

    def test_run_escalation_supervisor_after_threshold(self, seeded_temp_db):
        """Task at level 1 with notified_at past threshold gets supervisor escalation."""
        # Use 48 hours to clearly exceed the default 24-hour escalation threshold
        hours_past_threshold = 48
        repo = ClaimRepository()
        yesterday = (date.today() - timedelta(days=2)).isoformat()
        task_id = repo.create_task(
            "CLM-TEST001",
            "Supervisor escalation test",
            "other",
            due_date=yesterday,
        )
        # Manually mark notified with a timestamp far in the past
        old_time = (datetime.now(timezone.utc) - timedelta(hours=hours_past_threshold)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        with get_connection() as conn:
            conn.execute(
                "UPDATE claim_tasks SET escalation_level=1, escalation_notified_at=? WHERE id=?",
                (old_time, task_id),
            )

        with patch("claim_agent.diary.escalation.dispatch_webhook") as mock_webhook:
            result = run_deadline_escalation()

        assert result["escalated_count"] >= 1
        task = repo.get_task(task_id)
        assert task["escalation_level"] == 2
        assert task["escalation_escalated_at"] is not None
        dispatched_events = [call[0][0] for call in mock_webhook.call_args_list]
        assert "task.supervisor_escalated" in dispatched_events

    def test_run_escalation_no_escalation_below_threshold(self, seeded_temp_db):
        """Task at level 1 notified recently is NOT escalated to supervisor yet."""
        repo = ClaimRepository()
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        task_id = repo.create_task(
            "CLM-TEST001",
            "Below threshold test",
            "other",
            due_date=yesterday,
        )
        # Mark notified just now (well within threshold)
        repo.mark_task_overdue_notified(task_id)

        with patch("claim_agent.diary.escalation.dispatch_webhook"):
            result = run_deadline_escalation()

        assert result["escalated_count"] == 0
        task = repo.get_task(task_id)
        assert task["escalation_level"] == 1
