"""Tests for ERP adapter: MockERPAdapter, StubERPAdapter, inbound ERP webhook route."""

import hashlib
import hmac
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from claim_agent.adapters.mock.erp import MockERPAdapter
from claim_agent.adapters.stub import StubERPAdapter
from claim_agent.config import reload_settings
from claim_agent.mock_crew.erp import (
    capture_erp_event,
    clear_captured_erp_events,
    get_captured_erp_events,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ---------------------------------------------------------------------------
# MockERPAdapter – outbound (carrier → ERP)
# ---------------------------------------------------------------------------


class TestMockERPAdapterPushAssignment:
    def test_returns_erp_reference_and_status(self):
        adapter = MockERPAdapter()
        result = adapter.push_repair_assignment(
            claim_id="CLM-001",
            shop_id="SHOP-1",
            authorization_id="AUTH-A",
            repair_amount=3500.0,
            vehicle_info={"vin": "1HGBH41JXMN109186", "year": 2021},
        )
        assert "erp_reference" in result
        assert result["erp_reference"].startswith("ERP-ASSIGN-")
        assert result["status"] == "submitted"

    def test_records_assignment(self):
        adapter = MockERPAdapter()
        adapter.push_repair_assignment(
            claim_id="CLM-002",
            shop_id="SHOP-1",
            authorization_id=None,
            repair_amount=None,
            vehicle_info=None,
        )
        records = adapter.get_pushed_assignments()
        assert len(records) == 1
        assert records[0]["claim_id"] == "CLM-002"
        assert records[0]["shop_id"] == "SHOP-1"
        assert records[0]["authorization_id"] is None

    def test_vehicle_info_deep_copied(self):
        adapter = MockERPAdapter()
        vinfo = {"vin": "1HGBH41JXMN109186"}
        adapter.push_repair_assignment(
            claim_id="CLM-003",
            shop_id="SHOP-1",
            authorization_id=None,
            repair_amount=None,
            vehicle_info=vinfo,
        )
        vinfo["vin"] = "mutated"
        records = adapter.get_pushed_assignments()
        assert records[0]["vehicle_info"]["vin"] == "1HGBH41JXMN109186"


class TestMockERPAdapterPushEstimate:
    def test_returns_erp_reference_and_status(self):
        adapter = MockERPAdapter()
        result = adapter.push_estimate_update(
            claim_id="CLM-010",
            shop_id="SHOP-2",
            authorization_id="AUTH-B",
            estimate_amount=2800.50,
            line_items=[{"description": "Bumper", "quantity": 1, "unit_price": 800.0}],
            is_supplement=False,
        )
        assert result["erp_reference"].startswith("ERP-EST-")
        assert result["status"] == "submitted"

    def test_records_estimate_update(self):
        adapter = MockERPAdapter()
        adapter.push_estimate_update(
            claim_id="CLM-011",
            shop_id="SHOP-2",
            authorization_id=None,
            estimate_amount=1500.0,
            line_items=None,
            is_supplement=True,
        )
        records = adapter.get_pushed_estimate_updates()
        assert len(records) == 1
        assert records[0]["estimate_amount"] == 1500.0
        assert records[0]["is_supplement"] is True

    def test_amount_rounded_to_two_decimals(self):
        adapter = MockERPAdapter()
        adapter.push_estimate_update(
            claim_id="CLM-012",
            shop_id="SHOP-2",
            authorization_id=None,
            estimate_amount=1234.5678,
            line_items=None,
            is_supplement=False,
        )
        records = adapter.get_pushed_estimate_updates()
        assert records[0]["estimate_amount"] == 1234.57


class TestMockERPAdapterPushStatus:
    def test_returns_erp_reference_and_status(self):
        adapter = MockERPAdapter()
        result = adapter.push_repair_status(
            claim_id="CLM-020",
            shop_id="SHOP-3",
            authorization_id="AUTH-C",
            status="parts_ordered",
            notes="Waiting on bumper",
        )
        assert result["erp_reference"].startswith("ERP-STATUS-")
        assert result["status"] == "submitted"

    def test_records_status_update(self):
        adapter = MockERPAdapter()
        adapter.push_repair_status(
            claim_id="CLM-021",
            shop_id="SHOP-3",
            authorization_id=None,
            status="ready",
            notes=None,
        )
        records = adapter.get_pushed_status_updates()
        assert len(records) == 1
        assert records[0]["status"] == "ready"
        assert records[0]["claim_id"] == "CLM-021"


# ---------------------------------------------------------------------------
# MockERPAdapter – inbound (ERP → carrier polling)
# ---------------------------------------------------------------------------


class TestMockERPAdapterPullEvents:
    def test_empty_when_no_events_seeded(self):
        adapter = MockERPAdapter()
        assert adapter.pull_pending_events() == []

    def test_returns_seeded_event(self):
        adapter = MockERPAdapter()
        adapter.seed_pending_event({
            "event_type": "estimate_approved",
            "claim_id": "CLM-030",
            "shop_id": "SHOP-4",
            "erp_event_id": "ERP-EVT-001",
            "occurred_at": "2025-06-01T10:00:00Z",
            "approved_amount": 3000.0,
        })
        events = adapter.pull_pending_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "estimate_approved"
        assert events[0]["claim_id"] == "CLM-030"
        assert events[0]["approved_amount"] == 3000.0

    def test_drains_queue_on_pull(self):
        adapter = MockERPAdapter()
        adapter.seed_pending_event({
            "event_type": "parts_delayed",
            "claim_id": "CLM-031",
            "shop_id": "SHOP-4",
            "erp_event_id": "ERP-EVT-002",
            "occurred_at": "2025-06-01T11:00:00Z",
        })
        first = adapter.pull_pending_events()
        second = adapter.pull_pending_events()
        assert len(first) == 1
        assert second == []

    def test_filters_by_shop_id(self):
        adapter = MockERPAdapter()
        adapter.seed_pending_event({
            "event_type": "estimate_approved",
            "claim_id": "CLM-032",
            "shop_id": "SHOP-A",
            "erp_event_id": "ERP-EVT-003",
            "occurred_at": "2025-06-01T12:00:00Z",
        })
        adapter.seed_pending_event({
            "event_type": "parts_delayed",
            "claim_id": "CLM-033",
            "shop_id": "SHOP-B",
            "erp_event_id": "ERP-EVT-004",
            "occurred_at": "2025-06-01T12:01:00Z",
        })
        events = adapter.pull_pending_events(shop_id="SHOP-A")
        assert len(events) == 1
        assert events[0]["shop_id"] == "SHOP-A"

    def test_filters_by_since(self):
        adapter = MockERPAdapter()
        adapter.seed_pending_event({
            "event_type": "estimate_approved",
            "claim_id": "CLM-034",
            "shop_id": "SHOP-5",
            "erp_event_id": "ERP-EVT-005",
            "occurred_at": "2025-06-01T08:00:00Z",
        })
        adapter.seed_pending_event({
            "event_type": "parts_delayed",
            "claim_id": "CLM-035",
            "shop_id": "SHOP-5",
            "erp_event_id": "ERP-EVT-006",
            "occurred_at": "2025-06-02T08:00:00Z",
        })
        events = adapter.pull_pending_events(since="2025-06-01T09:00:00Z")
        # Only the second event is after the 'since' threshold
        assert len(events) == 1
        assert events[0]["claim_id"] == "CLM-035"

    def test_deep_copy_prevents_mutation(self):
        adapter = MockERPAdapter()
        original = {
            "event_type": "supplement_requested",
            "claim_id": "CLM-036",
            "shop_id": "SHOP-6",
            "erp_event_id": "ERP-EVT-007",
            "occurred_at": "2025-06-01T14:00:00Z",
            "supplement_amount": 500.0,
        }
        adapter.seed_pending_event(original)
        events = adapter.pull_pending_events()
        events[0]["supplement_amount"] = 999.0
        # Re-seed and pull again – original value must not be affected
        adapter.seed_pending_event(original)
        events2 = adapter.pull_pending_events()
        assert events2[0]["supplement_amount"] == 500.0


# ---------------------------------------------------------------------------
# MockERPAdapter – shop-ID identity mapping
# ---------------------------------------------------------------------------


class TestMockERPAdapterShopIdMapping:
    def test_default_identity_mapping(self):
        adapter = MockERPAdapter()
        assert adapter.resolve_shop_id("SHOP-XYZ") == "SHOP-XYZ"

    def test_custom_mapping(self):
        adapter = MockERPAdapter(shop_id_map={"SHOP-1": "42", "SHOP-2": "99"})
        assert adapter.resolve_shop_id("SHOP-1") == "42"
        assert adapter.resolve_shop_id("SHOP-2") == "99"
        assert adapter.resolve_shop_id("SHOP-UNKNOWN") == "SHOP-UNKNOWN"

    def test_mapping_applied_in_push(self):
        adapter = MockERPAdapter(shop_id_map={"SHOP-1": "erp-loc-42"})
        adapter.push_repair_assignment(
            claim_id="CLM-040",
            shop_id="SHOP-1",
            authorization_id=None,
            repair_amount=None,
            vehicle_info=None,
        )
        records = adapter.get_pushed_assignments()
        assert records[0]["erp_shop_id"] == "erp-loc-42"
        assert records[0]["shop_id"] == "SHOP-1"


# ---------------------------------------------------------------------------
# MockERPAdapter – clear_all helper
# ---------------------------------------------------------------------------


class TestMockERPAdapterClearAll:
    def test_clear_all_resets_all_stores(self):
        adapter = MockERPAdapter()
        adapter.push_repair_assignment(
            claim_id="CLM-050",
            shop_id="SHOP-1",
            authorization_id=None,
            repair_amount=None,
            vehicle_info=None,
        )
        adapter.push_estimate_update(
            claim_id="CLM-050",
            shop_id="SHOP-1",
            authorization_id=None,
            estimate_amount=1000.0,
            line_items=None,
            is_supplement=False,
        )
        adapter.push_repair_status(
            claim_id="CLM-050",
            shop_id="SHOP-1",
            authorization_id=None,
            status="received",
            notes=None,
        )
        adapter.seed_pending_event({
            "event_type": "estimate_approved",
            "claim_id": "CLM-050",
            "shop_id": "SHOP-1",
            "erp_event_id": "ERP-EVT-999",
            "occurred_at": "2025-06-01T00:00:00Z",
        })
        adapter.clear_all()
        assert adapter.get_pushed_assignments() == []
        assert adapter.get_pushed_estimate_updates() == []
        assert adapter.get_pushed_status_updates() == []
        assert adapter.pull_pending_events() == []


# ---------------------------------------------------------------------------
# StubERPAdapter – raises NotImplementedError for all methods
# ---------------------------------------------------------------------------


class TestStubERPAdapter:
    def _adapter(self) -> StubERPAdapter:
        return StubERPAdapter()

    def test_push_assignment_raises(self):
        with pytest.raises(NotImplementedError):
            self._adapter().push_repair_assignment(
                claim_id="X",
                shop_id="Y",
                authorization_id=None,
                repair_amount=None,
                vehicle_info=None,
            )

    def test_push_estimate_raises(self):
        with pytest.raises(NotImplementedError):
            self._adapter().push_estimate_update(
                claim_id="X",
                shop_id="Y",
                authorization_id=None,
                estimate_amount=100.0,
                line_items=None,
                is_supplement=False,
            )

    def test_push_status_raises(self):
        with pytest.raises(NotImplementedError):
            self._adapter().push_repair_status(
                claim_id="X",
                shop_id="Y",
                authorization_id=None,
                status="received",
                notes=None,
            )

    def test_pull_events_raises(self):
        with pytest.raises(NotImplementedError):
            self._adapter().pull_pending_events()

    def test_resolve_shop_id_uses_default_identity(self):
        assert self._adapter().resolve_shop_id("SHOP-Z") == "SHOP-Z"


# ---------------------------------------------------------------------------
# mock_crew/erp.py – capture / get / clear helpers
# ---------------------------------------------------------------------------


class TestMockERPCapture:
    def setup_method(self):
        clear_captured_erp_events()

    def test_capture_and_get_all(self):
        capture_erp_event("assignment", {"claim_id": "CLM-C01", "shop_id": "S1"})
        capture_erp_event("status", {"claim_id": "CLM-C02", "shop_id": "S2"})
        events = get_captured_erp_events()
        assert len(events) == 2

    def test_filter_by_event_type(self):
        capture_erp_event("assignment", {"claim_id": "CLM-C03", "shop_id": "S1"})
        capture_erp_event("estimate", {"claim_id": "CLM-C04", "shop_id": "S1"})
        assignment_events = get_captured_erp_events(event_type="assignment")
        assert len(assignment_events) == 1
        assert assignment_events[0]["claim_id"] == "CLM-C03"

    def test_get_does_not_drain(self):
        capture_erp_event("status", {"claim_id": "CLM-C05", "shop_id": "S1"})
        get_captured_erp_events()
        assert len(get_captured_erp_events()) == 1

    def test_clear_empties_store(self):
        capture_erp_event("assignment", {"claim_id": "CLM-C06", "shop_id": "S1"})
        clear_captured_erp_events()
        assert get_captured_erp_events() == []

    def test_payload_includes_event_type_tag(self):
        capture_erp_event("estimate", {"claim_id": "CLM-C07", "shop_id": "S1"})
        events = get_captured_erp_events()
        assert events[0]["_erp_event_type"] == "estimate"

    def test_mutation_does_not_affect_store(self):
        capture_erp_event("status", {"claim_id": "CLM-C08", "shop_id": "S1"})
        events = get_captured_erp_events()
        events[0]["claim_id"] = "mutated"
        assert get_captured_erp_events()[0]["claim_id"] == "CLM-C08"


# ---------------------------------------------------------------------------
# Inbound ERP webhook route (POST /api/webhooks/erp)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    yield


@pytest.fixture
def client():
    from claim_agent.api.server import app

    return TestClient(app)


_SECRET = "test-erp-secret"


def _erp_payload(overrides: dict | None = None) -> dict:
    base = {
        "event_type": "estimate_approved",
        "claim_id": "CLM-TEST005",
        "shop_id": "SHOP-001",
        "erp_event_id": "ERP-EVT-TEST-001",
        "occurred_at": "2025-06-01T10:00:00Z",
        "approved_amount": 1800.0,
    }
    if overrides:
        base.update(overrides)
    return base


def _post_erp(client, payload: dict, secret: str = _SECRET):
    body = json.dumps(payload).encode()
    sig = _sign(secret, body)
    return client.post(
        "/api/webhooks/erp",
        content=body,
        headers={"Content-Type": "application/json", "X-Webhook-Signature": sig},
    )


class TestERPWebhook:
    def test_estimate_approved_returns_200(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload())
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["event_type"] == "estimate_approved"
        assert body["claim_id"] == "CLM-TEST005"

    def test_parts_delayed_returns_200(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({
            "event_type": "parts_delayed",
            "delay_reason": "Supply chain disruption",
            "expected_availability_date": "2025-06-15",
        }))
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "parts_delayed"

    def test_supplement_requested_returns_200(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({
            "event_type": "supplement_requested",
            "supplement_amount": 500.0,
            "description": "Found additional frame damage",
        }))
        assert resp.status_code == 200
        assert resp.json()["event_type"] == "supplement_requested"

    def test_invalid_signature_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        body = json.dumps(_erp_payload()).encode()
        resp = client.post(
            "/api/webhooks/erp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Signature": "sha256=badbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadbadb",
            },
        )
        assert resp.status_code == 401

    def test_missing_signature_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        body = json.dumps(_erp_payload()).encode()
        resp = client.post(
            "/api/webhooks/erp",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_no_secret_configured_returns_401(self, client, monkeypatch):
        monkeypatch.delenv("WEBHOOK_SECRET", raising=False)
        reload_settings()
        resp = _post_erp(client, _erp_payload())
        assert resp.status_code == 401

    def test_invalid_json_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        body = b"not-json"
        sig = _sign(_SECRET, body)
        resp = client.post(
            "/api/webhooks/erp",
            content=body,
            headers={"Content-Type": "application/json", "X-Webhook-Signature": sig},
        )
        assert resp.status_code == 400

    def test_invalid_event_type_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({"event_type": "unknown_event"}))
        assert resp.status_code == 400
        assert "event_type" in resp.json()["detail"].lower()

    def test_unknown_claim_returns_404(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({"claim_id": "CLM-DOES-NOT-EXIST"}))
        assert resp.status_code == 404

    def test_missing_required_field_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        payload = _erp_payload()
        del payload["erp_event_id"]
        resp = _post_erp(client, payload)
        assert resp.status_code == 400

    def test_estimate_approved_unmatched_shop_returns_400(self, client, monkeypatch):
        """Shop ID not matching any partial_loss authorization → 400."""
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({"shop_id": "SHOP-UNKNOWN"}))
        assert resp.status_code == 400
        assert "authorization" in resp.json()["detail"].lower()

    def test_parts_delayed_unmatched_shop_returns_400(self, client, monkeypatch):
        """Parts-delayed event with unrecognized shop → 400."""
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({
            "event_type": "parts_delayed",
            "shop_id": "SHOP-UNKNOWN",
            "delay_reason": "Out of stock",
        }))
        assert resp.status_code == 400
        assert "authorization" in resp.json()["detail"].lower()

    def test_estimate_approved_db_failure_returns_500(self, client, monkeypatch):
        """DB write failure on estimate_approved → 500 (not swallowed)."""
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()

        def _raise_db_error(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "claim_agent.api.routes.webhooks.RepairStatusRepository.insert_repair_status",
            _raise_db_error,
        )
        resp = _post_erp(client, _erp_payload())
        assert resp.status_code == 500
        assert "repair status" in resp.json()["detail"].lower()

    def test_parts_delayed_db_failure_returns_500(self, client, monkeypatch):
        """DB write failure on parts_delayed → 500 (not swallowed)."""
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()

        def _raise_db_error(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "claim_agent.api.routes.webhooks.RepairStatusRepository.insert_repair_status",
            _raise_db_error,
        )
        resp = _post_erp(client, _erp_payload({
            "event_type": "parts_delayed",
            "delay_reason": "Supply chain disruption",
            "expected_availability_date": "2025-06-15",
        }))
        assert resp.status_code == 500
        assert "repair status" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Adapter registry – get_erp_adapter() returns mock by default
# ---------------------------------------------------------------------------


class TestERPAdapterRegistry:
    def test_default_backend_is_mock(self, monkeypatch):
        monkeypatch.delenv("ERP_ADAPTER", raising=False)
        reload_settings()
        from claim_agent.adapters.registry import get_erp_adapter, reset_adapters
        reset_adapters()
        adapter = get_erp_adapter()
        assert isinstance(adapter, MockERPAdapter)
        reset_adapters()

    def test_stub_backend(self, monkeypatch):
        monkeypatch.setenv("ERP_ADAPTER", "stub")
        reload_settings()
        from claim_agent.adapters.registry import get_erp_adapter, reset_adapters
        reset_adapters()
        adapter = get_erp_adapter()
        assert isinstance(adapter, StubERPAdapter)
        reset_adapters()

    def test_invalid_backend_raises(self, monkeypatch):
        monkeypatch.setenv("ERP_ADAPTER", "invalid_value")
        reload_settings()
        from claim_agent.adapters.registry import get_erp_adapter, reset_adapters
        reset_adapters()
        with pytest.raises(ValueError, match="ERP_ADAPTER"):
            get_erp_adapter()
        reset_adapters()

    def test_rest_requires_base_url(self, monkeypatch):
        monkeypatch.setenv("ERP_ADAPTER", "rest")
        monkeypatch.delenv("ERP_REST_BASE_URL", raising=False)
        reload_settings()
        from claim_agent.adapters.registry import get_erp_adapter, reset_adapters
        reset_adapters()
        with pytest.raises(ValueError, match="ERP_REST_BASE_URL"):
            get_erp_adapter()
        reset_adapters()


# ---------------------------------------------------------------------------
# MockERPAdapter – submission_status field naming consistency
# ---------------------------------------------------------------------------


class TestMockERPAdapterSubmissionStatus:
    """Records use 'submission_status' for submission result, 'status' for domain value."""

    def test_assignment_record_has_submission_status(self):
        adapter = MockERPAdapter()
        adapter.push_repair_assignment(
            claim_id="CLM-SS-001",
            shop_id="SHOP-1",
            authorization_id=None,
            repair_amount=1000.0,
            vehicle_info=None,
        )
        record = adapter.get_pushed_assignments()[0]
        assert record["submission_status"] == "submitted"
        assert "push_status" not in record

    def test_estimate_record_has_submission_status(self):
        adapter = MockERPAdapter()
        adapter.push_estimate_update(
            claim_id="CLM-SS-002",
            shop_id="SHOP-1",
            authorization_id=None,
            estimate_amount=2000.0,
            line_items=None,
            is_supplement=False,
        )
        record = adapter.get_pushed_estimate_updates()[0]
        assert record["submission_status"] == "submitted"
        assert "push_status" not in record

    def test_status_record_has_submission_status_and_domain_status(self):
        adapter = MockERPAdapter()
        adapter.push_repair_status(
            claim_id="CLM-SS-003",
            shop_id="SHOP-1",
            authorization_id=None,
            status="parts_ordered",
            notes=None,
        )
        record = adapter.get_pushed_status_updates()[0]
        # Domain repair status
        assert record["status"] == "parts_ordered"
        # Submission result
        assert record["submission_status"] == "submitted"
        assert "push_status" not in record


# ---------------------------------------------------------------------------
# RestERPAdapter – unit tests (AdapterHttpClient stubbed)
# ---------------------------------------------------------------------------


class _FakeResponse:
    status_code = 200

    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


class _FakeHttpClient:
    """Minimal AdapterHttpClient stub that records calls."""

    def __init__(self, **kw):
        self.posted: list[dict] = []
        self.get_calls: list[dict] = []
        self._response_data: Any = {"erp_reference": "REF-001", "status": "submitted"}

    def post(self, path, *, params=None, json=None):
        self.posted.append({"path": path, "json": json})
        return _FakeResponse(self._response_data)

    def get(self, path, *, params=None):
        self.get_calls.append({"path": path, "params": params})
        return _FakeResponse(self._response_data)


class TestRestERPAdapterPushAssignment:
    def test_posts_to_assignment_path(self, monkeypatch):
        stub = _FakeHttpClient()
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        adapter.push_repair_assignment(
            claim_id="CLM-R001",
            shop_id="SHOP-1",
            authorization_id="AUTH-X",
            repair_amount=3500.0,
            vehicle_info={"vin": "VIN123"},
        )
        assert len(stub.posted) == 1
        assert stub.posted[0]["path"] == "/repairs/assignment"
        body = stub.posted[0]["json"]
        assert body["claim_id"] == "CLM-R001"
        assert body["authorization_id"] == "AUTH-X"
        assert body["repair_amount"] == 3500.0

    def test_shop_id_mapping_applied(self, monkeypatch):
        stub = _FakeHttpClient()
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(
            base_url="https://erp.example.com",
            shop_id_map={"SHOP-1": "erp-loc-42"},
        )
        adapter.push_repair_assignment(
            claim_id="CLM-R002",
            shop_id="SHOP-1",
            authorization_id=None,
            repair_amount=None,
            vehicle_info=None,
        )
        assert stub.posted[0]["json"]["shop_id"] == "erp-loc-42"

    def test_returns_normalized_result(self, monkeypatch):
        stub = _FakeHttpClient()
        stub._response_data = {"erp_reference": "ERP-ABC", "status": "accepted"}
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        result = adapter.push_repair_assignment(
            claim_id="CLM-R003",
            shop_id="SHOP-2",
            authorization_id=None,
            repair_amount=None,
            vehicle_info=None,
        )
        assert result["erp_reference"] == "ERP-ABC"
        assert result["status"] == "accepted"


class TestRestERPAdapterPushEstimate:
    def test_amount_rounded_to_two_decimals(self, monkeypatch):
        stub = _FakeHttpClient()
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        adapter.push_estimate_update(
            claim_id="CLM-E001",
            shop_id="SHOP-1",
            authorization_id=None,
            estimate_amount=1234.5678,
            line_items=None,
            is_supplement=False,
        )
        assert stub.posted[0]["json"]["estimate_amount"] == 1234.57

    def test_posts_to_estimate_path(self, monkeypatch):
        stub = _FakeHttpClient()
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com", estimate_path="/v2/estimate")
        adapter.push_estimate_update(
            claim_id="CLM-E002",
            shop_id="SHOP-1",
            authorization_id=None,
            estimate_amount=500.0,
            line_items=[{"part": "bumper"}],
            is_supplement=True,
        )
        assert stub.posted[0]["path"] == "/v2/estimate"
        body = stub.posted[0]["json"]
        assert body["is_supplement"] is True
        assert body["line_items"] == [{"part": "bumper"}]


class TestRestERPAdapterPushStatus:
    def test_posts_status_and_notes(self, monkeypatch):
        stub = _FakeHttpClient()
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        adapter.push_repair_status(
            claim_id="CLM-S001",
            shop_id="SHOP-3",
            authorization_id="AUTH-Z",
            status="repair",
            notes="Frame work done",
        )
        body = stub.posted[0]["json"]
        assert body["status"] == "repair"
        assert body["notes"] == "Frame work done"
        assert body["authorization_id"] == "AUTH-Z"

    def test_shop_id_mapping_applied(self, monkeypatch):
        stub = _FakeHttpClient()
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(
            base_url="https://erp.example.com",
            shop_id_map={"SHOP-3": "99"},
        )
        adapter.push_repair_status(
            claim_id="CLM-S002",
            shop_id="SHOP-3",
            authorization_id=None,
            status="qa",
            notes=None,
        )
        assert stub.posted[0]["json"]["shop_id"] == "99"


class TestRestERPAdapterPullEvents:
    def test_passes_shop_id_and_since_params(self, monkeypatch):
        stub = _FakeHttpClient()
        stub._response_data = []
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(
            base_url="https://erp.example.com",
            shop_id_map={"SHOP-1": "42"},
        )
        adapter.pull_pending_events(shop_id="SHOP-1", since="2025-06-01T00:00:00Z")
        params = stub.get_calls[0]["params"]
        assert params["shop_id"] == "42"
        assert params["since"] == "2025-06-01T00:00:00Z"

    def test_returns_list_from_events_key(self, monkeypatch):
        stub = _FakeHttpClient()
        stub._response_data = {
            "events": [
                {"event_type": "estimate_approved", "claim_id": "CLM-P001"},
                {"event_type": "parts_delayed", "claim_id": "CLM-P002"},
            ]
        }
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        events = adapter.pull_pending_events()
        assert len(events) == 2
        assert events[0]["claim_id"] == "CLM-P001"

    def test_returns_bare_list_response(self, monkeypatch):
        stub = _FakeHttpClient()
        stub._response_data = [{"event_type": "supplement_requested", "claim_id": "CLM-P003"}]
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        events = adapter.pull_pending_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "supplement_requested"

    def test_filters_non_dict_items(self, monkeypatch):
        stub = _FakeHttpClient()
        stub._response_data = [{"event_type": "parts_delayed"}, "bad-item", 42]
        monkeypatch.setattr("claim_agent.adapters.real.erp_rest.AdapterHttpClient", lambda **kw: stub)
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        events = adapter.pull_pending_events()
        assert len(events) == 1


class TestExtractResult:
    def test_normalizes_erp_reference_and_status(self):
        from claim_agent.adapters.real.erp_rest import _extract_result

        result = _extract_result({"erp_reference": "REF-123", "status": "accepted"})
        assert result["erp_reference"] == "REF-123"
        assert result["status"] == "accepted"

    def test_falls_back_to_reference_field(self):
        from claim_agent.adapters.real.erp_rest import _extract_result

        result = _extract_result({"reference": "REF-456", "status": "submitted"})
        assert result["erp_reference"] == "REF-456"

    def test_falls_back_to_id_field(self):
        from claim_agent.adapters.real.erp_rest import _extract_result

        result = _extract_result({"id": "ID-789"})
        assert result["erp_reference"] == "ID-789"
        assert result["status"] == "submitted"

    def test_non_dict_returns_defaults(self):
        from claim_agent.adapters.real.erp_rest import _extract_result

        result = _extract_result("not-a-dict")
        assert result["erp_reference"] == ""
        assert result["status"] == "unknown"

    def test_passes_through_optional_fields(self):
        from claim_agent.adapters.real.erp_rest import _extract_result

        result = _extract_result({
            "erp_reference": "REF-X",
            "status": "accepted",
            "approved_amount": 2000.0,
            "message": "OK",
        })
        assert result["approved_amount"] == 2000.0
        assert result["message"] == "OK"


class TestCreateRestERPAdapterFactory:
    def test_raises_without_base_url(self, monkeypatch):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()  # base_url defaults to ""

        class FakeSettings:
            erp_rest = cfg

        monkeypatch.setattr(
            "claim_agent.adapters.real.erp_rest.get_settings", lambda: FakeSettings()
        )
        from claim_agent.adapters.real.erp_rest import create_rest_erp_adapter

        with pytest.raises(ValueError, match="ERP_REST_BASE_URL"):
            create_rest_erp_adapter()

    def test_builds_adapter_with_correct_config(self, monkeypatch):
        from claim_agent.config.settings_model import ERPRestConfig
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        cfg = ERPRestConfig()
        cfg.base_url = "https://erp.example.com/v2"
        cfg.auth_value = "Bearer tok"
        cfg.assignment_path = "/v2/repairs/assignment"
        cfg.timeout = 30.0

        class FakeSettings:
            erp_rest = cfg

        monkeypatch.setattr(
            "claim_agent.adapters.real.erp_rest.get_settings", lambda: FakeSettings()
        )
        monkeypatch.setattr(
            "claim_agent.adapters.real.erp_rest.AdapterHttpClient",
            lambda **kw: object(),
        )
        from claim_agent.adapters.real.erp_rest import create_rest_erp_adapter

        adapter = create_rest_erp_adapter()
        assert isinstance(adapter, RestERPAdapter)
        assert adapter._assignment_path == "/v2/repairs/assignment"


# ---------------------------------------------------------------------------
# ERP webhook – non-partial_loss claim type returns 400
# ---------------------------------------------------------------------------


class TestERPWebhookNonPartialLoss:
    def test_estimate_approved_non_partial_loss_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({
            "claim_id": "CLM-TEST002",
            "event_type": "estimate_approved",
        }))
        assert resp.status_code == 400
        body = resp.json()
        assert "partial_loss" in body["detail"].lower()
        assert body["erp_event_id"] == "ERP-EVT-TEST-001"

    def test_parts_delayed_non_partial_loss_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({
            "claim_id": "CLM-TEST002",
            "event_type": "parts_delayed",
        }))
        assert resp.status_code == 400
        assert "partial_loss" in resp.json()["detail"].lower()

    def test_supplement_requested_non_partial_loss_returns_400(self, client, monkeypatch):
        """supplement_requested follows the same partial_loss + authorization rules as other ERP events."""
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({
            "claim_id": "CLM-TEST002",
            "event_type": "supplement_requested",
            "supplement_amount": 200.0,
        }))
        assert resp.status_code == 400
        assert "partial_loss" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# ERP webhook – idempotency (duplicate erp_event_id)
# ---------------------------------------------------------------------------


class TestERPWebhookIdempotency:
    def test_duplicate_estimate_approved_returns_already_processed(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        payload = _erp_payload({"erp_event_id": "ERP-IDEMPOTENT-001"})
        resp1 = _post_erp(client, payload)
        assert resp1.status_code == 200
        assert resp1.json().get("already_processed") is not True

        resp2 = _post_erp(client, payload)
        assert resp2.status_code == 200
        body2 = resp2.json()
        assert body2["ok"] is True
        assert body2["already_processed"] is True
        assert body2["erp_event_id"] == "ERP-IDEMPOTENT-001"

    def test_duplicate_parts_delayed_returns_already_processed(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        payload = _erp_payload({
            "event_type": "parts_delayed",
            "erp_event_id": "ERP-IDEMPOTENT-002",
            "delay_reason": "Backordered",
        })
        resp1 = _post_erp(client, payload)
        assert resp1.status_code == 200

        resp2 = _post_erp(client, payload)
        assert resp2.status_code == 200
        assert resp2.json()["already_processed"] is True

    def test_duplicate_supplement_requested_returns_already_processed(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        payload = _erp_payload({
            "event_type": "supplement_requested",
            "erp_event_id": "ERP-IDEMPOTENT-SUPP-001",
            "supplement_amount": 250.0,
            "description": "Additional labor",
        })
        resp1 = _post_erp(client, payload)
        assert resp1.status_code == 200
        assert resp1.json().get("already_processed") is not True

        resp2 = _post_erp(client, payload)
        assert resp2.status_code == 200
        assert resp2.json()["already_processed"] is True


# ---------------------------------------------------------------------------
# ERP webhook – error responses include erp_event_id
# ---------------------------------------------------------------------------


class TestERPWebhookErrorResponseFields:
    def test_invalid_event_type_includes_erp_event_id(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({"event_type": "bad_type"}))
        assert resp.status_code == 400
        assert resp.json()["erp_event_id"] == "ERP-EVT-TEST-001"

    def test_claim_not_found_includes_erp_event_id(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({"claim_id": "CLM-NOPE"}))
        assert resp.status_code == 404
        assert resp.json()["erp_event_id"] == "ERP-EVT-TEST-001"

    def test_non_partial_loss_includes_erp_event_id(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload({"claim_id": "CLM-TEST002"}))
        assert resp.status_code == 400
        assert resp.json()["erp_event_id"] == "ERP-EVT-TEST-001"

    def test_db_failure_includes_erp_event_id(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()

        def _raise_db_error(*a, **kw):
            raise RuntimeError("db down")

        monkeypatch.setattr(
            "claim_agent.api.routes.webhooks.RepairStatusRepository.insert_repair_status",
            _raise_db_error,
        )
        monkeypatch.setattr(
            "claim_agent.api.routes.webhooks.RepairStatusRepository.has_erp_event",
            lambda *a, **kw: False,
        )
        resp = _post_erp(client, _erp_payload())
        assert resp.status_code == 500
        assert resp.json()["erp_event_id"] == "ERP-EVT-TEST-001"

    def test_success_includes_erp_event_id(self, client, monkeypatch):
        monkeypatch.setenv("WEBHOOK_SECRET", _SECRET)
        reload_settings()
        resp = _post_erp(client, _erp_payload())
        assert resp.status_code == 200
        assert resp.json()["erp_event_id"] == "ERP-EVT-TEST-001"


# ---------------------------------------------------------------------------
# ERPRestConfig.shop_id_map parsing edge cases
# ---------------------------------------------------------------------------


class TestERPRestConfigShopIdMapParsing:
    def test_empty_string(self):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()
        cfg.shop_id_map_raw = ""
        assert cfg.shop_id_map == {}

    def test_single_pair(self):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()
        cfg.shop_id_map_raw = "SHOP-1=42"
        assert cfg.shop_id_map == {"SHOP-1": "42"}

    def test_multiple_pairs(self):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()
        cfg.shop_id_map_raw = "SHOP-1=42,SHOP-2=99"
        assert cfg.shop_id_map == {"SHOP-1": "42", "SHOP-2": "99"}

    def test_trailing_comma_ignored(self):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()
        cfg.shop_id_map_raw = "SHOP-1=42,"
        assert cfg.shop_id_map == {"SHOP-1": "42"}

    def test_empty_value_skipped(self):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()
        cfg.shop_id_map_raw = "SHOP-1=,"
        assert cfg.shop_id_map == {}

    def test_empty_key_skipped(self):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()
        cfg.shop_id_map_raw = "=42"
        assert cfg.shop_id_map == {}

    def test_whitespace_trimmed(self):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()
        cfg.shop_id_map_raw = " SHOP-1 = 42 , SHOP-2 = 99 "
        assert cfg.shop_id_map == {"SHOP-1": "42", "SHOP-2": "99"}

    def test_malformed_no_equals(self):
        from claim_agent.config.settings_model import ERPRestConfig

        cfg = ERPRestConfig()
        cfg.shop_id_map_raw = "SHOP-1,SHOP-2=99"
        assert cfg.shop_id_map == {"SHOP-2": "99"}


# ---------------------------------------------------------------------------
# RestERPAdapter – CircuitOpenError in pull_pending_events
# ---------------------------------------------------------------------------


class TestRestERPAdapterCircuitBreaker:
    def test_pull_pending_events_returns_empty_on_circuit_open(self, monkeypatch):
        from claim_agent.adapters.http_client import CircuitOpenError

        class _CircuitOpenClient:
            def __init__(self, **kw):
                pass

            def get(self, path, *, params=None):
                raise CircuitOpenError("circuit open")

        monkeypatch.setattr(
            "claim_agent.adapters.real.erp_rest.AdapterHttpClient", _CircuitOpenClient
        )
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        events = adapter.pull_pending_events()
        assert events == []

    def test_push_assignment_propagates_circuit_open(self, monkeypatch):
        from claim_agent.adapters.http_client import CircuitOpenError

        class _CircuitOpenClient:
            def __init__(self, **kw):
                pass

            def post(self, path, *, params=None, json=None):
                raise CircuitOpenError("circuit open")

        monkeypatch.setattr(
            "claim_agent.adapters.real.erp_rest.AdapterHttpClient", _CircuitOpenClient
        )
        from claim_agent.adapters.real.erp_rest import RestERPAdapter

        adapter = RestERPAdapter(base_url="https://erp.example.com")
        with pytest.raises(CircuitOpenError):
            adapter.push_repair_assignment(
                claim_id="CLM-X",
                shop_id="SHOP-1",
                authorization_id=None,
                repair_amount=None,
                vehicle_info=None,
            )
