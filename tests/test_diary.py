"""Tests for diary system: recurrence, templates, escalation."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from sqlalchemy import text

from claim_agent.db.database import get_connection
from claim_agent.db.repository import ClaimRepository
from claim_agent.diary.auto_create import ensure_diary_listener_registered
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

    def test_get_templates_archived_to_purged_no_match(self):
        templates = get_status_transition_templates("archived", "purged")
        assert len(templates) == 0


class TestAutoCreateDiaryListener:
    """Tests for auto-create diary entries at claim status transitions."""

    def test_status_transition_creates_diary_tasks(self, seeded_temp_db):
        """Status transition (open->settled) triggers diary task creation."""
        ensure_diary_listener_registered()
        repo = ClaimRepository()

        # CLM-TEST001 is open with payout; transition to settled
        repo.update_claim_status("CLM-TEST001", "settled", details="Settlement complete")

        tasks, _ = repo.get_tasks_for_claim("CLM-TEST001")
        diary_tasks = [t for t in tasks if t.get("auto_created_from", "").startswith("status_transition:")]
        assert len(diary_tasks) >= 1
        verify_task = next(
            (t for t in diary_tasks if "Verify settlement" in t.get("title", "")),
            None,
        )
        assert verify_task is not None
        assert verify_task["auto_created_from"] == "status_transition:open->settled"
        assert verify_task["created_by"] == "diary_system"
        # due_days=1 from template
        expected_due = (date.today() + timedelta(days=1)).isoformat()
        assert verify_task["due_date"] == expected_due

    def test_status_transition_pending_to_processing_creates_recurring_task(self, seeded_temp_db):
        """pending->processing creates task with recurrence_rule and recurrence_interval."""
        ensure_diary_listener_registered()
        repo = ClaimRepository()

        # Create claim (starts as pending), then transition to processing
        from claim_agent.models.claim import ClaimInput

        claim_input = ClaimInput(
            policy_number="POL-AUTO",
            vin="1HGBH41JXMN109001",
            vehicle_year=2022,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Test",
            damage_description="Test damage",
        )
        claim_id = repo.create_claim(claim_input)
        repo.update_claim_status(claim_id, "processing", details="Started processing")

        tasks, _ = repo.get_tasks_for_claim(claim_id)
        diary_tasks = [t for t in tasks if t.get("auto_created_from", "").startswith("status_transition:")]
        assert len(diary_tasks) >= 1
        follow_up = next(
            (t for t in diary_tasks if "Follow up on claim processing" in t.get("title", "")),
            None,
        )
        assert follow_up is not None
        assert follow_up["auto_created_from"] == "status_transition:pending->processing"
        assert follow_up["recurrence_rule"] == "interval_days"
        assert follow_up["recurrence_interval"] == 3


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
        mock_webhook.assert_called_once()
        call_event, call_payload = mock_webhook.call_args[0]
        assert call_event == "task.overdue"
        assert call_payload["task_id"] == task_id
        assert call_payload["claim_id"] == "CLM-TEST001"
        assert call_payload["due_date"] == yesterday

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
                text("UPDATE claim_tasks SET escalation_level=1, escalation_notified_at=:t WHERE id=:id"),
                {"t": old_time, "id": task_id},
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
