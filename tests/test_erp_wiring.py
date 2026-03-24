"""Tests for ERP adapter wiring in the partial-loss repair workflow.

Covers:
- push_repair_assignment() called by assign_repair_shop_impl()
- push_repair_assignment() + push_estimate_update() + push_repair_status()
  called by generate_repair_authorization_impl()
- push_estimate_update(is_supplement=True) + push_repair_status()
  called by update_repair_authorization_impl()
- capture_erp_event() invoked when MOCK_CREW_ENABLED + MOCK_ERP_CAPTURE_ENABLED
- _run_erp_poll_job() calls pull_pending_events() and logs results
"""

import json
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

# Ensure mock DB is found before any claim_agent imports
os.environ.setdefault(
    "MOCK_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_erp_adapter(**kwargs: Any) -> MagicMock:
    """Return a MagicMock that behaves like an ERPAdapter."""
    adapter = MagicMock()
    defaults = {
        "push_repair_assignment.return_value": {"erp_reference": "ERP-ASSIGN-TEST", "status": "submitted"},
        "push_estimate_update.return_value": {"erp_reference": "ERP-EST-TEST", "status": "submitted"},
        "push_repair_status.return_value": {"erp_reference": "ERP-STATUS-TEST", "status": "submitted"},
        "pull_pending_events.return_value": [],
    }
    for attr, val in {**defaults, **kwargs}.items():
        parts = attr.split(".")
        obj = adapter
        for part in parts[:-1]:
            obj = getattr(obj, part)
        setattr(obj, parts[-1], val)
    return adapter


# ---------------------------------------------------------------------------
# assign_repair_shop_impl – ERP push_repair_assignment
# ---------------------------------------------------------------------------


class TestAssignRepairShopERPPush:
    def test_push_assignment_called_on_success(self):
        """push_repair_assignment is called when a shop is successfully assigned."""
        from claim_agent.tools.partial_loss_logic import assign_repair_shop_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = assign_repair_shop_impl("CLM-ERP-001", "SHOP-001", 5)

        data = json.loads(result)
        assert data["success"] is True
        mock_adapter.push_repair_assignment.assert_called_once()
        call_kwargs = mock_adapter.push_repair_assignment.call_args.kwargs
        assert call_kwargs["claim_id"] == "CLM-ERP-001"
        assert call_kwargs["shop_id"] == "SHOP-001"
        assert call_kwargs["authorization_id"] is None

    def test_erp_reference_stored_in_result(self):
        """erp_reference from the adapter is included in the assignment result."""
        from claim_agent.tools.partial_loss_logic import assign_repair_shop_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = assign_repair_shop_impl("CLM-ERP-002", "SHOP-001", 5)

        data = json.loads(result)
        assert data.get("erp_reference") == "ERP-ASSIGN-TEST"

    def test_erp_failure_is_non_fatal(self):
        """ERP push failure does not prevent successful shop assignment."""
        from claim_agent.tools.partial_loss_logic import assign_repair_shop_impl

        mock_adapter = MagicMock()
        mock_adapter.push_repair_assignment.side_effect = RuntimeError("ERP down")
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = assign_repair_shop_impl("CLM-ERP-003", "SHOP-001", 5)

        data = json.loads(result)
        assert data["success"] is True
        assert "erp_reference" not in data

    def test_push_not_called_when_shop_not_found(self):
        """ERP adapter is not called when the shop does not exist."""
        from claim_agent.tools.partial_loss_logic import assign_repair_shop_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = assign_repair_shop_impl("CLM-ERP-004", "SHOP-NOTFOUND", 5)

        data = json.loads(result)
        assert data["success"] is False
        mock_adapter.push_repair_assignment.assert_not_called()


# ---------------------------------------------------------------------------
# generate_repair_authorization_impl – ERP push calls
# ---------------------------------------------------------------------------


class TestGenerateRepairAuthorizationERPPush:
    _ESTIMATE = {
        "total_estimate": 3500.0,
        "parts_cost": 2000.0,
        "labor_cost": 1500.0,
        "deductible": 500.0,
        "customer_pays": 500.0,
        "insurance_pays": 3000.0,
        "part_type_preference": "aftermarket",
    }

    def test_push_assignment_called_with_auth_id(self):
        """push_repair_assignment is called with the generated authorization_id."""
        from claim_agent.tools.partial_loss_logic import generate_repair_authorization_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = generate_repair_authorization_impl(
                claim_id="CLM-AUTH-001",
                shop_id="SHOP-001",
                repair_estimate=self._ESTIMATE,
            )

        data = json.loads(result)
        assert "authorization_id" in data
        auth_id = data["authorization_id"]
        assert auth_id.startswith("RA-")

        mock_adapter.push_repair_assignment.assert_called_once()
        call_kw = mock_adapter.push_repair_assignment.call_args.kwargs
        assert call_kw["claim_id"] == "CLM-AUTH-001"
        assert call_kw["shop_id"] == "SHOP-001"
        assert call_kw["authorization_id"] == auth_id
        assert call_kw["repair_amount"] == 3500.0

    def test_push_estimate_called(self):
        """push_estimate_update is called with the authorized amount."""
        from claim_agent.tools.partial_loss_logic import generate_repair_authorization_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = generate_repair_authorization_impl(
                claim_id="CLM-AUTH-002",
                shop_id="SHOP-001",
                repair_estimate=self._ESTIMATE,
            )

        data = json.loads(result)
        mock_adapter.push_estimate_update.assert_called_once()
        call_kw = mock_adapter.push_estimate_update.call_args.kwargs
        assert call_kw["claim_id"] == "CLM-AUTH-002"
        assert call_kw["estimate_amount"] == 3500.0
        assert call_kw["is_supplement"] is False
        assert call_kw["authorization_id"] == data["authorization_id"]

    def test_push_status_received_called(self):
        """push_repair_status(status='received') is called after authorization."""
        from claim_agent.tools.partial_loss_logic import generate_repair_authorization_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            generate_repair_authorization_impl(
                claim_id="CLM-AUTH-003",
                shop_id="SHOP-001",
                repair_estimate=self._ESTIMATE,
            )

        mock_adapter.push_repair_status.assert_called_once()
        call_kw = mock_adapter.push_repair_status.call_args.kwargs
        assert call_kw["claim_id"] == "CLM-AUTH-003"
        assert call_kw["status"] == "received"

    def test_erp_reference_stored_in_result(self):
        """erp_reference from push_repair_assignment is stored in the authorization."""
        from claim_agent.tools.partial_loss_logic import generate_repair_authorization_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = generate_repair_authorization_impl(
                claim_id="CLM-AUTH-004",
                shop_id="SHOP-001",
                repair_estimate=self._ESTIMATE,
            )

        data = json.loads(result)
        assert data.get("erp_reference") == "ERP-ASSIGN-TEST"

    def test_erp_failure_is_non_fatal(self):
        """ERP push failure does not prevent authorization creation."""
        from claim_agent.tools.partial_loss_logic import generate_repair_authorization_impl

        mock_adapter = MagicMock()
        mock_adapter.push_repair_assignment.side_effect = RuntimeError("ERP down")
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = generate_repair_authorization_impl(
                claim_id="CLM-AUTH-005",
                shop_id="SHOP-001",
                repair_estimate=self._ESTIMATE,
            )

        data = json.loads(result)
        assert "authorization_id" in data
        assert "erp_reference" not in data

    def test_pending_approval_does_not_push_erp(self):
        """No ERP push should occur until the customer approves authorization."""
        from claim_agent.tools.partial_loss_logic import generate_repair_authorization_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = generate_repair_authorization_impl(
                claim_id="CLM-AUTH-006",
                shop_id="SHOP-001",
                repair_estimate=self._ESTIMATE,
                customer_approved=False,
            )

        data = json.loads(result)
        assert data["authorization_status"] == "pending_approval"
        assert "erp_reference" not in data
        mock_adapter.push_repair_assignment.assert_not_called()
        mock_adapter.push_estimate_update.assert_not_called()
        mock_adapter.push_repair_status.assert_not_called()


# ---------------------------------------------------------------------------
# update_repair_authorization_impl – ERP push calls for supplement
# ---------------------------------------------------------------------------


class TestUpdateRepairAuthorizationERPPush:
    def test_push_estimate_supplement_called(self):
        """push_estimate_update(is_supplement=True) is called on supplemental update."""
        from claim_agent.tools.partial_loss_logic import update_repair_authorization_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = update_repair_authorization_impl(
                claim_id="CLM-SUP-001",
                shop_id="SHOP-001",
                original_total=3500.0,
                original_parts=2000.0,
                original_labor=1500.0,
                original_insurance_pays=3000.0,
                supplemental_total=800.0,
                supplemental_parts=500.0,
                supplemental_labor=300.0,
                supplemental_insurance_pays=800.0,
                authorization_id="RA-ORIGINAL",
            )

        data = json.loads(result)
        assert data["success"] is True

        mock_adapter.push_estimate_update.assert_called_once()
        call_kw = mock_adapter.push_estimate_update.call_args.kwargs
        assert call_kw["claim_id"] == "CLM-SUP-001"
        assert call_kw["estimate_amount"] == 800.0
        assert call_kw["is_supplement"] is True

    def test_push_status_supplemental_called(self):
        """push_repair_status(status='supplemental') is called on supplemental update."""
        from claim_agent.tools.partial_loss_logic import update_repair_authorization_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            update_repair_authorization_impl(
                claim_id="CLM-SUP-002",
                shop_id="SHOP-001",
                original_total=3500.0,
                original_parts=2000.0,
                original_labor=1500.0,
                original_insurance_pays=3000.0,
                supplemental_total=800.0,
                supplemental_parts=500.0,
                supplemental_labor=300.0,
                supplemental_insurance_pays=800.0,
            )

        mock_adapter.push_repair_status.assert_called_once()
        call_kw = mock_adapter.push_repair_status.call_args.kwargs
        assert call_kw["claim_id"] == "CLM-SUP-002"
        assert call_kw["status"] == "supplemental"

    def test_supplement_pending_approval_does_not_push_erp(self):
        """No supplemental ERP push until the customer approves the update."""
        from claim_agent.tools.partial_loss_logic import update_repair_authorization_impl

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = update_repair_authorization_impl(
                claim_id="CLM-SUP-PEND",
                shop_id="SHOP-001",
                original_total=3500.0,
                original_parts=2000.0,
                original_labor=1500.0,
                original_insurance_pays=3000.0,
                supplemental_total=800.0,
                supplemental_parts=500.0,
                supplemental_labor=300.0,
                supplemental_insurance_pays=800.0,
                authorization_id="RA-ORIGINAL",
                customer_approved=False,
            )

        data = json.loads(result)
        assert data["authorization_status"] == "pending_approval"
        mock_adapter.push_estimate_update.assert_not_called()
        mock_adapter.push_repair_status.assert_not_called()

    def test_erp_failure_is_non_fatal(self):
        """ERP push failure does not prevent supplemental authorization update."""
        from claim_agent.tools.partial_loss_logic import update_repair_authorization_impl

        mock_adapter = MagicMock()
        mock_adapter.push_estimate_update.side_effect = RuntimeError("ERP down")
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            result = update_repair_authorization_impl(
                claim_id="CLM-SUP-003",
                shop_id="SHOP-001",
                original_total=3500.0,
                original_parts=2000.0,
                original_labor=1500.0,
                original_insurance_pays=3000.0,
                supplemental_total=800.0,
                supplemental_parts=500.0,
                supplemental_labor=300.0,
                supplemental_insurance_pays=800.0,
            )

        data = json.loads(result)
        assert data["success"] is True


# ---------------------------------------------------------------------------
# Mock ERP capture wiring
# ---------------------------------------------------------------------------


class TestMockERPCaptureWiring:
    def test_capture_called_on_assign_when_enabled(self, monkeypatch):
        """capture_erp_event is called during assign_repair_shop_impl when capture enabled."""
        from claim_agent.config import reload_settings
        from claim_agent.mock_crew.erp import clear_captured_erp_events, get_captured_erp_events
        from claim_agent.tools.partial_loss_logic import assign_repair_shop_impl

        monkeypatch.setenv("MOCK_CREW_ENABLED", "true")
        monkeypatch.setenv("MOCK_ERP_CAPTURE_ENABLED", "true")
        reload_settings()
        clear_captured_erp_events()

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            assign_repair_shop_impl("CLM-CAP-001", "SHOP-001", 5)

        events = get_captured_erp_events(event_type="assignment")
        assert len(events) == 1
        assert events[0]["claim_id"] == "CLM-CAP-001"
        assert events[0]["_erp_event_type"] == "assignment"
        clear_captured_erp_events()

    def test_no_capture_when_disabled(self, monkeypatch):
        """capture_erp_event is NOT called when MOCK_ERP_CAPTURE_ENABLED=false."""
        from claim_agent.config import reload_settings
        from claim_agent.mock_crew.erp import clear_captured_erp_events, get_captured_erp_events
        from claim_agent.tools.partial_loss_logic import assign_repair_shop_impl

        monkeypatch.setenv("MOCK_CREW_ENABLED", "true")
        monkeypatch.setenv("MOCK_ERP_CAPTURE_ENABLED", "false")
        reload_settings()
        clear_captured_erp_events()

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            assign_repair_shop_impl("CLM-CAP-002", "SHOP-001", 5)

        events = get_captured_erp_events()
        assert events == []
        clear_captured_erp_events()

    def test_capture_all_three_events_on_authorization(self, monkeypatch):
        """Three events (assignment, estimate, status) captured during generate_repair_authorization."""
        from claim_agent.config import reload_settings
        from claim_agent.mock_crew.erp import clear_captured_erp_events, get_captured_erp_events
        from claim_agent.tools.partial_loss_logic import generate_repair_authorization_impl

        monkeypatch.setenv("MOCK_CREW_ENABLED", "true")
        monkeypatch.setenv("MOCK_ERP_CAPTURE_ENABLED", "true")
        reload_settings()
        clear_captured_erp_events()

        estimate = {
            "total_estimate": 3500.0,
            "parts_cost": 2000.0,
            "labor_cost": 1500.0,
            "deductible": 500.0,
            "customer_pays": 500.0,
            "insurance_pays": 3000.0,
        }
        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            generate_repair_authorization_impl(
                claim_id="CLM-CAP-003",
                shop_id="SHOP-001",
                repair_estimate=estimate,
            )

        all_events = get_captured_erp_events()
        types = [e["_erp_event_type"] for e in all_events]
        assert "assignment" in types
        assert "estimate" in types
        assert "status" in types
        clear_captured_erp_events()

    def test_capture_supplement_events(self, monkeypatch):
        """Supplement events (estimate, status) captured during update_repair_authorization."""
        from claim_agent.config import reload_settings
        from claim_agent.mock_crew.erp import clear_captured_erp_events, get_captured_erp_events
        from claim_agent.tools.partial_loss_logic import update_repair_authorization_impl

        monkeypatch.setenv("MOCK_CREW_ENABLED", "true")
        monkeypatch.setenv("MOCK_ERP_CAPTURE_ENABLED", "true")
        reload_settings()
        clear_captured_erp_events()

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.tools.partial_loss_logic.get_erp_adapter", return_value=mock_adapter):
            update_repair_authorization_impl(
                claim_id="CLM-CAP-004",
                shop_id="SHOP-001",
                original_total=3500.0,
                original_parts=2000.0,
                original_labor=1500.0,
                original_insurance_pays=3000.0,
                supplemental_total=800.0,
                supplemental_parts=500.0,
                supplemental_labor=300.0,
                supplemental_insurance_pays=800.0,
            )

        all_events = get_captured_erp_events()
        types = [e["_erp_event_type"] for e in all_events]
        assert "estimate" in types
        assert "status" in types

        est_events = get_captured_erp_events(event_type="estimate")
        assert est_events[0]["is_supplement"] is True
        clear_captured_erp_events()


# ---------------------------------------------------------------------------
# MockERPCaptureConfig settings
# ---------------------------------------------------------------------------


class TestMockERPCaptureConfig:
    def test_default_capture_disabled(self):
        from claim_agent.config.settings_model import MockERPCaptureConfig

        cfg = MockERPCaptureConfig()
        assert cfg.capture_enabled is False

    def test_capture_enabled_via_env(self, monkeypatch):
        from claim_agent.config.settings_model import MockERPCaptureConfig

        monkeypatch.setenv("MOCK_ERP_CAPTURE_ENABLED", "true")
        cfg = MockERPCaptureConfig()
        assert cfg.capture_enabled is True

    def test_get_mock_erp_capture_config_returns_dict(self, monkeypatch):
        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_mock_erp_capture_config

        monkeypatch.setenv("MOCK_ERP_CAPTURE_ENABLED", "true")
        reload_settings()
        cfg = get_mock_erp_capture_config()
        assert cfg["capture_enabled"] is True


# ---------------------------------------------------------------------------
# Scheduler ERP poll job
# ---------------------------------------------------------------------------


class TestERPPollJob:
    def test_poll_job_calls_pull_pending_events(self):
        """_run_erp_poll_job calls pull_pending_events on the ERP adapter."""
        from claim_agent.scheduler import _run_erp_poll_job

        mock_adapter = _make_mock_erp_adapter()
        with patch("claim_agent.adapters.registry.get_erp_adapter", return_value=mock_adapter):
            _run_erp_poll_job()

        mock_adapter.pull_pending_events.assert_called_once_with()

    def test_poll_job_processes_returned_events(self):
        """_run_erp_poll_job iterates over returned events."""
        from claim_agent.scheduler import _run_erp_poll_job

        events = [
            {
                "event_type": "estimate_approved",
                "claim_id": "CLM-POLL-001",
                "shop_id": "SHOP-1",
                "erp_event_id": "ERP-POLL-001",
                "occurred_at": "2025-06-01T10:00:00Z",
            }
        ]
        mock_adapter = _make_mock_erp_adapter(**{"pull_pending_events.return_value": events})
        with patch("claim_agent.adapters.registry.get_erp_adapter", return_value=mock_adapter):
            # Should not raise
            _run_erp_poll_job()

        mock_adapter.pull_pending_events.assert_called_once()

    def test_poll_job_records_estimate_approved_event(self, seeded_temp_db):
        """Polling path applies the same state updates as the webhook path."""
        from claim_agent.db.repair_status_repository import RepairStatusRepository
        from claim_agent.scheduler import _run_erp_poll_job

        events = [
            {
                "event_type": "estimate_approved",
                "claim_id": "CLM-TEST005",
                "shop_id": "SHOP-001",
                "erp_event_id": "ERP-POLL-APPLY-001",
                "occurred_at": "2025-06-01T10:00:00Z",
                "approved_amount": 2100.0,
            }
        ]
        mock_adapter = _make_mock_erp_adapter(**{"pull_pending_events.return_value": events})
        with patch("claim_agent.adapters.registry.get_erp_adapter", return_value=mock_adapter):
            _run_erp_poll_job()

        status_repo = RepairStatusRepository(db_path=seeded_temp_db)
        latest = status_repo.get_repair_status("CLM-TEST005")
        assert latest is not None
        assert latest["status"] == "repair"
        assert "ERP-POLL-APPLY-001" in (latest.get("notes") or "")

    def test_poll_job_survives_adapter_error(self):
        """_run_erp_poll_job catches and logs exceptions from the ERP adapter."""
        from claim_agent.scheduler import _run_erp_poll_job

        mock_adapter = MagicMock()
        mock_adapter.pull_pending_events.side_effect = RuntimeError("ERP unavailable")
        with patch("claim_agent.adapters.registry.get_erp_adapter", return_value=mock_adapter):
            # Should not raise
            _run_erp_poll_job()

    def test_erp_poll_cron_has_default(self):
        """SchedulerConfig.erp_poll_cron has a sensible default value."""
        from claim_agent.config.settings_model import SchedulerConfig

        cfg = SchedulerConfig()
        assert cfg.erp_poll_cron == "*/15 * * * *"

    def test_erp_poll_cron_env_override(self, monkeypatch):
        """SCHEDULER_ERP_POLL_CRON env var overrides the default."""
        from claim_agent.config.settings_model import SchedulerConfig

        monkeypatch.setenv("SCHEDULER_ERP_POLL_CRON", "0 * * * *")
        cfg = SchedulerConfig()
        assert cfg.erp_poll_cron == "0 * * * *"
