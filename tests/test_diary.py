"""Tests for diary system: recurrence, templates, escalation."""

import tempfile
from datetime import date, timedelta
from pathlib import Path
import pytest

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
