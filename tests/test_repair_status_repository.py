"""Unit tests for db/repair_status_repository."""

from claim_agent.db.repair_status_repository import (
    RepairStatusRepository,
    parse_iso_ts,
)


class TestParseIsoTs:
    def test_valid_iso(self):
        ts = parse_iso_ts("2025-01-15T10:30:00Z")
        assert ts is not None
        assert ts.year == 2025
        assert ts.month == 1
        assert ts.day == 15

    def test_none_returns_none(self):
        assert parse_iso_ts(None) is None

    def test_empty_returns_none(self):
        assert parse_iso_ts("") is None

    def test_invalid_returns_none(self):
        assert parse_iso_ts("not-a-date") is None


class TestRepairStatusRepository:
    """Uses seeded_temp_db so claims exist (repair_status has FK to claims)."""

    def test_insert_repair_status_returns_id(self, seeded_temp_db):
        repo = RepairStatusRepository(db_path=seeded_temp_db)
        row_id = repo.insert_repair_status(
            claim_id="CLM-TEST001",
            shop_id="SHOP-001",
            status="received",
        )
        assert row_id > 0

    def test_insert_with_optional_fields(self, seeded_temp_db):
        repo = RepairStatusRepository(db_path=seeded_temp_db)
        row_id = repo.insert_repair_status(
            claim_id="CLM-TEST002",
            shop_id="SHOP-002",
            status="in_progress",
            authorization_id="RA-123",
            notes="Parts ordered",
            paused_at=None,
            pause_reason=None,
        )
        assert row_id > 0

    def test_get_repair_status_returns_latest(self, seeded_temp_db):
        repo = RepairStatusRepository(db_path=seeded_temp_db)
        repo.insert_repair_status("CLM-TEST003", "SHOP-003", "received")
        repo.insert_repair_status("CLM-TEST003", "SHOP-003", "ready")
        latest = repo.get_repair_status("CLM-TEST003")
        assert latest is not None
        assert latest["status"] == "ready"
        assert latest["claim_id"] == "CLM-TEST003"
        assert latest["shop_id"] == "SHOP-003"

    def test_get_repair_status_none_for_unknown_claim(self, seeded_temp_db):
        repo = RepairStatusRepository(db_path=seeded_temp_db)
        assert repo.get_repair_status("CLM-UNKNOWN") is None

    def test_get_repair_status_history_oldest_first(self, seeded_temp_db):
        repo = RepairStatusRepository(db_path=seeded_temp_db)
        repo.insert_repair_status("CLM-TEST004", "SHOP-004", "received")
        repo.insert_repair_status("CLM-TEST004", "SHOP-004", "in_progress")
        repo.insert_repair_status("CLM-TEST004", "SHOP-004", "ready")
        history = repo.get_repair_status_history("CLM-TEST004", limit=10)
        assert len(history) == 3
        assert history[0]["status"] == "received"
        assert history[1]["status"] == "in_progress"
        assert history[2]["status"] == "ready"

    def test_get_cycle_time_days_returns_days(self, seeded_temp_db):
        repo = RepairStatusRepository(db_path=seeded_temp_db)
        repo.insert_repair_status("CLM-ARCHIVED", "SHOP-005", "received")
        repo.insert_repair_status("CLM-ARCHIVED", "SHOP-005", "ready")
        days = repo.get_cycle_time_days("CLM-ARCHIVED")
        assert days is not None
        assert days >= 0

    def test_get_cycle_time_days_none_when_incomplete(self, seeded_temp_db):
        repo = RepairStatusRepository(db_path=seeded_temp_db)
        # Only "received", no "ready" -> cycle time is None
        repo.insert_repair_status("CLM-TEST005", "SHOP-006", "received")
        days = repo.get_cycle_time_days("CLM-TEST005")
        assert days is None
