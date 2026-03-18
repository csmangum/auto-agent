"""Tests for the adapter layer: base ABCs, mock implementations, stubs, and registry."""


import pytest

from claim_agent.adapters.base import (
    ClaimSearchAdapter,
    OCRAdapter,
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    SIUAdapter,
    ValuationAdapter,
)
from claim_agent.adapters.mock import (
    MockClaimSearchAdapter,
    MockPartsAdapter,
    MockPolicyAdapter,
    MockRepairShopAdapter,
    MockSIUAdapter,
    MockValuationAdapter,
)
from claim_agent.adapters.mock.ocr import MockOCRAdapter
from claim_agent.adapters.registry import (
    get_claim_search_adapter,
    get_ocr_adapter,
    get_parts_adapter,
    get_policy_adapter,
    get_repair_shop_adapter,
    get_siu_adapter,
    get_valuation_adapter,
    reset_adapters,
)
from claim_agent.adapters.stub import (
    StubClaimSearchAdapter,
    StubOCRAdapter,
    StubPartsAdapter,
    StubPolicyAdapter,
    StubRepairShopAdapter,
    StubSIUAdapter,
    StubValuationAdapter,
)
from claim_agent.config import reload_settings


# ---------------------------------------------------------------------------
# ABC contract checks
# ---------------------------------------------------------------------------

class TestABCEnforcement:
    def test_policy_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            PolicyAdapter()  # type: ignore[abstract]

    def test_valuation_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            ValuationAdapter()  # type: ignore[abstract]

    def test_repair_shop_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            RepairShopAdapter()  # type: ignore[abstract]

    def test_parts_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            PartsAdapter()  # type: ignore[abstract]

    def test_siu_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            SIUAdapter()  # type: ignore[abstract]

    def test_claim_search_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            ClaimSearchAdapter()  # type: ignore[abstract]

    def test_ocr_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            OCRAdapter()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# Mock adapter unit tests
# ---------------------------------------------------------------------------

class TestMockPolicyAdapter:
    def test_known_policy(self):
        adapter = MockPolicyAdapter()
        result = adapter.get_policy("POL-001")
        assert result is not None
        assert "status" in result
        assert "coverages" in result or "coverage" in result
        assert (
            "collision_deductible" in result
            or "comprehensive_deductible" in result
            or "deductible" in result
        )

    def test_unknown_policy(self):
        adapter = MockPolicyAdapter()
        assert adapter.get_policy("DOES-NOT-EXIST") is None

    def test_implements_interface(self):
        assert isinstance(MockPolicyAdapter(), PolicyAdapter)


class TestMockValuationAdapter:
    def test_known_vin(self):
        adapter = MockValuationAdapter()
        from claim_agent.data.loader import load_mock_db
        db = load_mock_db()
        vins = list(db.get("vehicle_values", {}).keys())
        if vins:
            result = adapter.get_vehicle_value(vins[0], 2020, "", "")
            assert result is not None
            assert "value" in result

    def test_unknown_vehicle(self):
        adapter = MockValuationAdapter()
        result = adapter.get_vehicle_value("", 1900, "NoMake", "NoModel")
        assert result is None

    def test_implements_interface(self):
        assert isinstance(MockValuationAdapter(), ValuationAdapter)


class TestMockRepairShopAdapter:
    def test_get_shops_returns_dict(self):
        adapter = MockRepairShopAdapter()
        shops = adapter.get_shops()
        assert isinstance(shops, dict)
        assert len(shops) > 0

    def test_get_shop_known(self):
        adapter = MockRepairShopAdapter()
        shop = adapter.get_shop("SHOP-001")
        assert shop is not None
        assert "name" in shop

    def test_get_shop_unknown(self):
        adapter = MockRepairShopAdapter()
        assert adapter.get_shop("NO-SHOP") is None

    def test_get_labor_operations(self):
        adapter = MockRepairShopAdapter()
        ops = adapter.get_labor_operations()
        assert isinstance(ops, dict)

    def test_implements_interface(self):
        assert isinstance(MockRepairShopAdapter(), RepairShopAdapter)


class TestMockPartsAdapter:
    def test_get_catalog(self):
        adapter = MockPartsAdapter()
        catalog = adapter.get_catalog()
        assert isinstance(catalog, dict)
        assert len(catalog) > 0

    def test_implements_interface(self):
        assert isinstance(MockPartsAdapter(), PartsAdapter)


class TestMockSIUAdapter:
    def test_create_case_returns_id(self):
        adapter = MockSIUAdapter()
        case_id = adapter.create_case("CLM-001", ["staged"])
        assert isinstance(case_id, str)
        assert case_id.startswith("SIU-MOCK-")

    def test_get_case_returns_case_after_create(self):
        adapter = MockSIUAdapter()
        case_id = adapter.create_case("CLM-002", ["inflated"])
        case = adapter.get_case(case_id)
        assert case is not None
        assert case["case_id"] == case_id
        assert case["claim_id"] == "CLM-002"
        assert case["indicators"] == ["inflated"]
        assert case["status"] == "open"

    def test_add_investigation_note(self):
        adapter = MockSIUAdapter()
        case_id = adapter.create_case("CLM-003", ["staged"])
        ok = adapter.add_investigation_note(case_id, "Document verified", category="document_review")
        assert ok is True
        case = adapter.get_case(case_id)
        assert len(case["notes"]) == 1
        assert case["notes"][0]["category"] == "document_review"
        assert case["notes"][0]["note"] == "Document verified"

    def test_update_case_status(self):
        adapter = MockSIUAdapter()
        case_id = adapter.create_case("CLM-004", [])
        ok = adapter.update_case_status(case_id, "closed")
        assert ok is True
        case = adapter.get_case(case_id)
        assert case["status"] == "closed"

    def test_implements_interface(self):
        assert isinstance(MockSIUAdapter(), SIUAdapter)


class TestMockClaimSearchAdapter:
    def test_search_returns_list(self):
        adapter = MockClaimSearchAdapter()
        result = adapter.search_claims(vin="TEST-FRAUD-123")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_implements_interface(self):
        assert isinstance(MockClaimSearchAdapter(), ClaimSearchAdapter)


class TestMockOCRAdapter:
    def test_extract_estimate_returns_structured_data(self, tmp_path):
        adapter = MockOCRAdapter()
        path = tmp_path / "estimate.pdf"
        path.write_bytes(b"fake")
        result = adapter.extract_structured_data(path, "estimate")
        assert result is not None
        assert "line_items" in result
        assert "total" in result
        assert "parts_cost" in result
        assert "labor_cost" in result

    def test_extract_police_report_returns_structured_data(self, tmp_path):
        adapter = MockOCRAdapter()
        path = tmp_path / "report.pdf"
        path.write_bytes(b"fake")
        result = adapter.extract_structured_data(path, "police_report")
        assert result is not None
        assert "incident_date" in result
        assert "report_number" in result
        assert "parties" in result

    def test_extract_medical_record_returns_structured_data(self, tmp_path):
        adapter = MockOCRAdapter()
        path = tmp_path / "medical.pdf"
        path.write_bytes(b"fake")
        result = adapter.extract_structured_data(path, "medical_record")
        assert result is not None
        assert "diagnoses" in result
        assert "charges" in result
        assert "provider" in result

    def test_extract_unsupported_type_returns_none(self, tmp_path):
        adapter = MockOCRAdapter()
        path = tmp_path / "other.pdf"
        path.write_bytes(b"fake")
        result = adapter.extract_structured_data(path, "other")
        assert result is None

    def test_implements_interface(self):
        assert isinstance(MockOCRAdapter(), OCRAdapter)


class TestStubOCRAdapter:
    def test_extract_returns_none(self, tmp_path):
        adapter = StubOCRAdapter()
        path = tmp_path / "doc.pdf"
        path.write_bytes(b"fake")
        result = adapter.extract_structured_data(path, "estimate")
        assert result is None


# ---------------------------------------------------------------------------
# Stub adapter tests
# ---------------------------------------------------------------------------

class TestStubAdapters:
    def test_stub_policy_raises(self):
        with pytest.raises(NotImplementedError, match="StubPolicyAdapter"):
            StubPolicyAdapter().get_policy("POL-001")

    def test_stub_valuation_raises(self):
        with pytest.raises(NotImplementedError, match="StubValuationAdapter"):
            StubValuationAdapter().get_vehicle_value("VIN", 2020, "Ford", "Focus")

    def test_stub_repair_shop_get_shops_raises(self):
        with pytest.raises(NotImplementedError, match="StubRepairShopAdapter"):
            StubRepairShopAdapter().get_shops()

    def test_stub_repair_shop_get_shop_raises(self):
        with pytest.raises(NotImplementedError, match="StubRepairShopAdapter"):
            StubRepairShopAdapter().get_shop("SHOP-001")

    def test_stub_repair_shop_labor_ops_raises(self):
        with pytest.raises(NotImplementedError, match="StubRepairShopAdapter"):
            StubRepairShopAdapter().get_labor_operations()

    def test_stub_parts_raises(self):
        with pytest.raises(NotImplementedError, match="StubPartsAdapter"):
            StubPartsAdapter().get_catalog()

    def test_stub_siu_raises(self):
        with pytest.raises(NotImplementedError, match="StubSIUAdapter"):
            StubSIUAdapter().create_case("CLM-001", ["staged"])

    def test_stub_claim_search_raises(self):
        with pytest.raises(NotImplementedError, match="StubClaimSearchAdapter"):
            StubClaimSearchAdapter().search_claims(vin="VIN123")


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_default_backend_is_mock(self):
        reset_adapters()
        assert isinstance(get_policy_adapter(), MockPolicyAdapter)
        assert isinstance(get_valuation_adapter(), MockValuationAdapter)
        assert isinstance(get_repair_shop_adapter(), MockRepairShopAdapter)
        assert isinstance(get_parts_adapter(), MockPartsAdapter)
        assert isinstance(get_siu_adapter(), MockSIUAdapter)
        assert isinstance(get_claim_search_adapter(), MockClaimSearchAdapter)
        assert isinstance(get_ocr_adapter(), MockOCRAdapter)

    def test_stub_backend_via_env(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "stub")
        monkeypatch.setenv("VALUATION_ADAPTER", "stub")
        monkeypatch.setenv("REPAIR_SHOP_ADAPTER", "stub")
        monkeypatch.setenv("PARTS_ADAPTER", "stub")
        monkeypatch.setenv("SIU_ADAPTER", "stub")
        monkeypatch.setenv("CLAIM_SEARCH_ADAPTER", "stub")
        monkeypatch.setenv("OCR_ADAPTER", "stub")
        reload_settings()
        assert isinstance(get_policy_adapter(), StubPolicyAdapter)
        assert isinstance(get_valuation_adapter(), StubValuationAdapter)
        assert isinstance(get_repair_shop_adapter(), StubRepairShopAdapter)
        assert isinstance(get_parts_adapter(), StubPartsAdapter)
        assert isinstance(get_siu_adapter(), StubSIUAdapter)
        assert isinstance(get_claim_search_adapter(), StubClaimSearchAdapter)
        assert isinstance(get_ocr_adapter(), StubOCRAdapter)

    def test_singleton_returns_same_instance(self):
        reset_adapters()
        a = get_policy_adapter()
        b = get_policy_adapter()
        assert a is b

    def test_reset_clears_singletons(self):
        a = get_policy_adapter()
        reset_adapters()
        b = get_policy_adapter()
        assert a is not b

    def test_invalid_backend_raises(self, monkeypatch):
        """Unknown backend value raises ValueError with helpful message."""
        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "rest")
        reload_settings()
        with pytest.raises(ValueError, match="Unknown POLICY_ADAPTER backend.*rest"):
            get_policy_adapter()


# ---------------------------------------------------------------------------
# Adapter caller tests: logic that catches NotImplementedError from stubs
# ---------------------------------------------------------------------------

class TestValuationLogicStubFallback:
    """When StubValuationAdapter raises, fetch_vehicle_value falls back to default."""

    def test_stub_adapter_returns_default_value(self, monkeypatch):
        from claim_agent.tools.valuation_logic import fetch_vehicle_value_impl

        reset_adapters()
        monkeypatch.setenv("VALUATION_ADAPTER", "stub")
        result = fetch_vehicle_value_impl("VIN123", 2021, "Honda", "Civic")
        import json
        data = json.loads(result)
        assert "value" in data
        assert data["value"] >= 0
        assert data["condition"] == "good"
        assert "source" in data


class TestPolicyLogicStubRaises:
    """When StubPolicyAdapter raises NotImplementedError, query_policy_db_impl raises AdapterError."""

    def test_stub_adapter_raises_adapter_error(self, monkeypatch):
        from claim_agent.exceptions import AdapterError
        from claim_agent.tools.policy_logic import query_policy_db_impl

        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "stub")
        reload_settings()
        with pytest.raises(AdapterError, match="not supported"):
            query_policy_db_impl("POL-001")
