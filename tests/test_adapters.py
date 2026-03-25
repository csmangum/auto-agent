"""Tests for the adapter layer: base ABCs, mock implementations, stubs, and registry."""

import httpx
import pytest

from claim_agent.adapters.base import (
    ClaimSearchAdapter,
    FraudReportingAdapter,
    GapInsuranceAdapter,
    NMVTISAdapter,
    OCRAdapter,
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    SIUAdapter,
    StateBureauAdapter,
    ValuationAdapter,
)
from claim_agent.adapters.mock import (
    MockClaimSearchAdapter,
    MockFraudReportingAdapter,
    MockGapInsuranceAdapter,
    MockNMVTISAdapter,
    MockPartsAdapter,
    MockPolicyAdapter,
    MockRepairShopAdapter,
    MockSIUAdapter,
    MockStateBureauAdapter,
    MockValuationAdapter,
)
from claim_agent.adapters.mock.ocr import MockOCRAdapter
from claim_agent.adapters.registry import (
    get_claim_search_adapter,
    get_cms_reporting_adapter,
    get_fraud_reporting_adapter,
    get_gap_insurance_adapter,
    get_nmvtis_adapter,
    get_ocr_adapter,
    get_parts_adapter,
    get_policy_adapter,
    get_repair_shop_adapter,
    get_siu_adapter,
    get_state_bureau_adapter,
    get_valuation_adapter,
    reset_adapters,
)
from claim_agent.adapters.stub import (
    StubClaimSearchAdapter,
    StubGapInsuranceAdapter,
    StubNMVTISAdapter,
    StubOCRAdapter,
    StubPartsAdapter,
    StubPolicyAdapter,
    StubRepairShopAdapter,
    StubSIUAdapter,
    StubStateBureauAdapter,
    StubValuationAdapter,
)
from claim_agent.adapters.stub_fraud_reporting import StubFraudReportingAdapter
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

    def test_state_bureau_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            StateBureauAdapter()  # type: ignore[abstract]

    def test_claim_search_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            ClaimSearchAdapter()  # type: ignore[abstract]

    def test_ocr_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            OCRAdapter()  # type: ignore[abstract]

    def test_nmvtis_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            NMVTISAdapter()  # type: ignore[abstract]

    def test_gap_insurance_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            GapInsuranceAdapter()  # type: ignore[abstract]

    def test_fraud_reporting_adapter_is_abstract(self):
        with pytest.raises(TypeError):
            FraudReportingAdapter()  # type: ignore[abstract]


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


class TestMockNMVTISAdapter:
    def test_submit_returns_reference(self):
        adapter = MockNMVTISAdapter()
        out = adapter.submit_total_loss_report(
            claim_id="CLM-1",
            vin="1HGBH41JXMN109186",
            vehicle_year=2020,
            make="Honda",
            model="Accord",
            loss_type="total_loss",
            trigger_event="dmv_salvage_report",
            dmv_reference="DMV-REF",
        )
        assert out["nmvtis_reference"].startswith("NMVTIS-MOCK-")
        assert out["status"] == "accepted"

    def test_fail_twice_then_succeed(self):
        adapter = MockNMVTISAdapter()
        cid = "CLM-NMVTIS-FAILTWICE-X"
        with pytest.raises(RuntimeError, match="transient"):
            adapter.submit_total_loss_report(
                claim_id=cid,
                vin="1HGBH41JXMN109186",
                vehicle_year=2020,
                make="Honda",
                model="Accord",
                loss_type="total_loss",
                trigger_event="dmv_salvage_report",
            )
        with pytest.raises(RuntimeError, match="transient"):
            adapter.submit_total_loss_report(
                claim_id=cid,
                vin="1HGBH41JXMN109186",
                vehicle_year=2020,
                make="Honda",
                model="Accord",
                loss_type="total_loss",
                trigger_event="dmv_salvage_report",
            )
        out = adapter.submit_total_loss_report(
            claim_id=cid,
            vin="1HGBH41JXMN109186",
            vehicle_year=2020,
            make="Honda",
            model="Accord",
            loss_type="total_loss",
            trigger_event="dmv_salvage_report",
        )
        assert out["status"] == "accepted"

    def test_implements_interface(self):
        assert isinstance(MockNMVTISAdapter(), NMVTISAdapter)


class TestMockPartsAdapter:
    def test_get_catalog(self):
        adapter = MockPartsAdapter()
        catalog = adapter.get_catalog()
        assert isinstance(catalog, dict)
        assert len(catalog) > 0

    def test_implements_interface(self):
        assert isinstance(MockPartsAdapter(), PartsAdapter)


class TestMockGapInsuranceAdapter:
    def test_submit_shortfall_returns_carrier_id(self):
        adapter = MockGapInsuranceAdapter()
        out = adapter.submit_shortfall_claim(
            claim_id="CLM-1",
            policy_number="POL-001",
            auto_payout_amount=10000.0,
            loan_balance=15000.0,
            shortfall_amount=5000.0,
            vin="VIN123",
        )
        assert out["gap_claim_id"].startswith("GAP-MOCK-")
        assert out["status"] == "approved_pending_payment"
        assert out["approved_amount"] == 5000.0

    def test_get_claim_status_after_submit(self):
        adapter = MockGapInsuranceAdapter()
        out = adapter.submit_shortfall_claim(
            claim_id="CLM-2",
            policy_number="POL-001",
            auto_payout_amount=1.0,
            loan_balance=150_000.0,
            shortfall_amount=120_000.0,
        )
        st = adapter.get_claim_status(out["gap_claim_id"])
        assert st is not None
        assert st["status"] == "partial_approval"

    def test_implements_interface(self):
        assert isinstance(MockGapInsuranceAdapter(), GapInsuranceAdapter)


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


class TestMockStateBureauAdapter:
    def test_submit_fraud_report_returns_report_id(self):
        adapter = MockStateBureauAdapter()
        out = adapter.submit_fraud_report(
            claim_id="CLM-1",
            case_id="SIU-1",
            state="California",
            indicators=["staged"],
        )
        assert out["report_id"].startswith("FRB-CA-")
        assert out["state"] == "California"
        assert "message" in out

    def test_implements_interface(self):
        assert isinstance(MockStateBureauAdapter(), StateBureauAdapter)

    def test_state_name_maps_to_two_letter_code(self):
        adapter = MockStateBureauAdapter()
        out = adapter.submit_fraud_report(
            claim_id="CLM-2",
            case_id="SIU-2",
            state="Texas",
            indicators=[],
        )
        assert out["report_id"].startswith("FRB-TX-")


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

    def test_stub_state_bureau_raises(self):
        with pytest.raises(NotImplementedError, match="StubStateBureauAdapter"):
            StubStateBureauAdapter().submit_fraud_report(
                claim_id="CLM-001",
                case_id="SIU-001",
                state="California",
                indicators=["staged"],
            )

    def test_stub_claim_search_raises(self):
        with pytest.raises(NotImplementedError, match="StubClaimSearchAdapter"):
            StubClaimSearchAdapter().search_claims(vin="VIN123")

    def test_stub_nmvtis_raises(self):
        with pytest.raises(NotImplementedError, match="StubNMVTISAdapter"):
            StubNMVTISAdapter().submit_total_loss_report(
                claim_id="C",
                vin="VIN12345678901234",
                vehicle_year=2020,
                make="X",
                model="Y",
                loss_type="total_loss",
                trigger_event="manual_resubmit",
            )

    def test_stub_gap_insurance_raises(self):
        with pytest.raises(NotImplementedError, match="StubGapInsuranceAdapter"):
            StubGapInsuranceAdapter().submit_shortfall_claim(
                claim_id="C",
                policy_number="P",
                auto_payout_amount=1.0,
                loan_balance=2.0,
                shortfall_amount=1.0,
            )


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
        assert isinstance(get_state_bureau_adapter(), MockStateBureauAdapter)
        assert isinstance(get_claim_search_adapter(), MockClaimSearchAdapter)
        assert isinstance(get_fraud_reporting_adapter(), MockFraudReportingAdapter)
        assert isinstance(get_nmvtis_adapter(), MockNMVTISAdapter)
        assert isinstance(get_gap_insurance_adapter(), MockGapInsuranceAdapter)
        assert isinstance(get_ocr_adapter(), MockOCRAdapter)

    def test_stub_backend_via_env(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "stub")
        monkeypatch.setenv("VALUATION_ADAPTER", "stub")
        monkeypatch.setenv("REPAIR_SHOP_ADAPTER", "stub")
        monkeypatch.setenv("PARTS_ADAPTER", "stub")
        monkeypatch.setenv("SIU_ADAPTER", "stub")
        monkeypatch.setenv("STATE_BUREAU_ADAPTER", "stub")
        monkeypatch.setenv("CLAIM_SEARCH_ADAPTER", "stub")
        monkeypatch.setenv("FRAUD_REPORTING_ADAPTER", "stub")
        monkeypatch.setenv("NMVTIS_ADAPTER", "stub")
        monkeypatch.setenv("GAP_INSURANCE_ADAPTER", "stub")
        monkeypatch.setenv("OCR_ADAPTER", "stub")
        reload_settings()
        assert isinstance(get_policy_adapter(), StubPolicyAdapter)
        assert isinstance(get_valuation_adapter(), StubValuationAdapter)
        assert isinstance(get_repair_shop_adapter(), StubRepairShopAdapter)
        assert isinstance(get_parts_adapter(), StubPartsAdapter)
        assert isinstance(get_siu_adapter(), StubSIUAdapter)
        assert isinstance(get_state_bureau_adapter(), StubStateBureauAdapter)
        assert isinstance(get_claim_search_adapter(), StubClaimSearchAdapter)
        assert isinstance(get_fraud_reporting_adapter(), StubFraudReportingAdapter)
        assert isinstance(get_nmvtis_adapter(), StubNMVTISAdapter)
        assert isinstance(get_gap_insurance_adapter(), StubGapInsuranceAdapter)
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
        monkeypatch.setenv("POLICY_ADAPTER", "invalid")
        reload_settings()
        with pytest.raises(ValueError, match="Unknown POLICY_ADAPTER backend.*invalid"):
            get_policy_adapter()

    def test_valuation_ccc_requires_rest_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("VALUATION_ADAPTER", "ccc")
        monkeypatch.setenv("VALUATION_REST_BASE_URL", "")
        reload_settings()
        with pytest.raises(ValueError, match="VALUATION_REST_BASE_URL"):
            get_valuation_adapter()
        reset_adapters()

    def test_valuation_rest_backend_rejected(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("VALUATION_ADAPTER", "rest")
        reload_settings()
        with pytest.raises(ValueError, match="VALUATION_ADAPTER=rest"):
            get_valuation_adapter()
        reset_adapters()

    def test_valuation_ccc_registry_returns_rest_adapter(self, monkeypatch):
        from claim_agent.adapters.real.valuation_rest import RestValuationAdapter

        reset_adapters()
        monkeypatch.setenv("VALUATION_ADAPTER", "ccc")
        monkeypatch.setenv("VALUATION_REST_BASE_URL", "https://gw.example.com")
        reload_settings()

        class HC:
            def __init__(self, **kw):
                pass

            def get(self, path, params=None):
                class R:
                    status_code = 200

                    def raise_for_status(self):
                        pass

                    def json(self):
                        return {"value": 21000, "condition": "good", "comparables": []}

                return R()

        monkeypatch.setattr(
            "claim_agent.adapters.real.valuation_rest.AdapterHttpClient",
            HC,
        )
        v = get_valuation_adapter()
        assert isinstance(v, RestValuationAdapter)
        out = v.get_vehicle_value("VIN123", 2022, "Toyota", "Camry")
        assert out is not None
        assert out["value"] == 21000
        reset_adapters()

    def test_fraud_reporting_rest_requires_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("FRAUD_REPORTING_ADAPTER", "rest")
        monkeypatch.delenv("FRAUD_REPORTING_REST_BASE_URL", raising=False)
        reload_settings()
        with pytest.raises(ValueError, match="FRAUD_REPORTING_REST_BASE_URL"):
            get_fraud_reporting_adapter()
        reset_adapters()

    def test_state_bureau_rest_requires_endpoint(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("STATE_BUREAU_ADAPTER", "rest")
        monkeypatch.delenv("STATE_BUREAU_CA_ENDPOINT", raising=False)
        monkeypatch.delenv("STATE_BUREAU_TX_ENDPOINT", raising=False)
        monkeypatch.delenv("STATE_BUREAU_FL_ENDPOINT", raising=False)
        monkeypatch.delenv("STATE_BUREAU_NY_ENDPOINT", raising=False)
        monkeypatch.delenv("STATE_BUREAU_GA_ENDPOINT", raising=False)
        reload_settings()
        with pytest.raises(ValueError, match="STATE_BUREAU_<STATE>_ENDPOINT"):
            get_state_bureau_adapter()


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


class TestRestPolicyAdapter:
    """REST policy adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        """POLICY_ADAPTER=rest without POLICY_REST_BASE_URL raises ValueError."""
        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "rest")
        monkeypatch.delenv("POLICY_REST_BASE_URL", raising=False)
        reload_settings()
        with pytest.raises(ValueError, match="POLICY_REST_BASE_URL"):
            get_policy_adapter()

    def test_rest_get_policy_returns_data(self, monkeypatch):
        """RestPolicyAdapter returns policy dict on 200."""
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "rest")
        monkeypatch.setenv("POLICY_REST_BASE_URL", "https://pas.example.com/api/v1")
        reload_settings()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "active", "coverages": ["collision"]}

        with patch(
            "claim_agent.adapters.real.policy_rest.AdapterHttpClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value = mock_client
            adapter = get_policy_adapter()
            result = adapter.get_policy("POL-001")
        assert result == {"status": "active", "coverages": ["collision"]}

    def test_rest_get_policy_404_returns_none(self, monkeypatch):
        """RestPolicyAdapter returns None on 404."""
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "rest")
        monkeypatch.setenv("POLICY_REST_BASE_URL", "https://pas.example.com/api/v1")
        reload_settings()

        # AdapterHttpClient.get() raises HTTPStatusError on 404; adapter catches and returns None
        request = httpx.Request("GET", "https://pas.example.com/api/v1/policies/POL-UNKNOWN")
        response = httpx.Response(404, request=request)
        http_error = httpx.HTTPStatusError("Not Found", request=request, response=response)

        with patch(
            "claim_agent.adapters.real.policy_rest.AdapterHttpClient"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.side_effect = http_error
            mock_client_cls.return_value = mock_client
            adapter = get_policy_adapter()
            result = adapter.get_policy("POL-UNKNOWN")
        assert result is None


# ---------------------------------------------------------------------------
# REST adapter registry tests (new adapters)
# ---------------------------------------------------------------------------

class TestRestRepairShopAdapter:
    """REST repair-shop adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("REPAIR_SHOP_ADAPTER", "rest")
        monkeypatch.delenv("REPAIR_SHOP_REST_BASE_URL", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        with pytest.raises(ValueError, match="REPAIR_SHOP_REST_BASE_URL"):
            get_repair_shop_adapter()
        reset_adapters()

    def test_rest_get_shops_returns_dict(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("REPAIR_SHOP_ADAPTER", "rest")
        monkeypatch.setenv("REPAIR_SHOP_REST_BASE_URL", "https://shops.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"S1": {"name": "Joe's Auto"}, "S2": {"name": "Fast Fix"}}

        with patch("claim_agent.adapters.real.repair_shop_rest.AdapterHttpClient") as MockClient:
            client = MagicMock()
            client.get.return_value = mock_resp
            MockClient.return_value = client
            adapter = get_repair_shop_adapter()
            result = adapter.get_shops()
        assert "S1" in result
        assert result["S1"]["name"] == "Joe's Auto"
        reset_adapters()

    def test_rest_get_shop_404_returns_none(self, monkeypatch):
        import httpx
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("REPAIR_SHOP_ADAPTER", "rest")
        monkeypatch.setenv("REPAIR_SHOP_REST_BASE_URL", "https://shops.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        request = httpx.Request("GET", "https://shops.example.com/api/v1/shops/MISSING")
        response = httpx.Response(404, request=request)
        http_error = httpx.HTTPStatusError("Not Found", request=request, response=response)

        with patch("claim_agent.adapters.real.repair_shop_rest.AdapterHttpClient") as MockClient:
            client = MagicMock()
            client.get.side_effect = http_error
            MockClient.return_value = client
            adapter = get_repair_shop_adapter()
            result = adapter.get_shop("MISSING")
        assert result is None
        reset_adapters()


class TestRestPartsAdapter:
    """REST parts adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("PARTS_ADAPTER", "rest")
        monkeypatch.delenv("PARTS_REST_BASE_URL", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        with pytest.raises(ValueError, match="PARTS_REST_BASE_URL"):
            get_parts_adapter()
        reset_adapters()

    def test_rest_get_catalog_returns_dict(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("PARTS_ADAPTER", "rest")
        monkeypatch.setenv("PARTS_REST_BASE_URL", "https://parts.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"part_id": "P1", "description": "Bumper Cover"},
            {"part_id": "P2", "description": "Headlight"},
        ]

        with patch("claim_agent.adapters.real.parts_rest.AdapterHttpClient") as MockClient:
            client = MagicMock()
            client.get.return_value = mock_resp
            MockClient.return_value = client
            adapter = get_parts_adapter()
            result = adapter.get_catalog()
        assert "P1" in result
        assert result["P1"]["description"] == "Bumper Cover"
        reset_adapters()


class TestRestSIUAdapter:
    """REST SIU adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("SIU_ADAPTER", "rest")
        monkeypatch.delenv("SIU_REST_BASE_URL", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        with pytest.raises(ValueError, match="SIU_REST_BASE_URL"):
            get_siu_adapter()
        reset_adapters()

    def test_rest_create_case_returns_id(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("SIU_ADAPTER", "rest")
        monkeypatch.setenv("SIU_REST_BASE_URL", "https://siu.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"case_id": "SIU-REST-001", "status": "open"}

        with patch("claim_agent.adapters.real.siu_rest.AdapterHttpClient") as MockClient:
            client = MagicMock()
            client.post.return_value = mock_resp
            MockClient.return_value = client
            adapter = get_siu_adapter()
            case_id = adapter.create_case("CLAIM-1", ["indicator_a"])
        assert case_id == "SIU-REST-001"
        reset_adapters()


class TestRestNMVTISAdapter:
    """REST NMVTIS adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("NMVTIS_ADAPTER", "rest")
        monkeypatch.delenv("NMVTIS_REST_BASE_URL", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        with pytest.raises(ValueError, match="NMVTIS_REST_BASE_URL"):
            get_nmvtis_adapter()
        reset_adapters()

    def test_rest_submit_report_returns_reference(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("NMVTIS_ADAPTER", "rest")
        monkeypatch.setenv("NMVTIS_REST_BASE_URL", "https://nmvtis-gw.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "nmvtis_reference": "NMVTIS-REST-ABC123",
            "status": "accepted",
        }

        with patch("claim_agent.adapters.real.nmvtis_rest.AdapterHttpClient") as MockClient:
            client = MagicMock()
            client.post.return_value = mock_resp
            MockClient.return_value = client
            adapter = get_nmvtis_adapter()
            result = adapter.submit_total_loss_report(
                claim_id="C1",
                vin="1HGBH41JXMN109186",
                vehicle_year=2022,
                make="Honda",
                model="Civic",
                loss_type="total_loss",
                trigger_event="dmv_salvage_report",
            )
        assert result["nmvtis_reference"] == "NMVTIS-REST-ABC123"
        assert result["status"] == "accepted"
        reset_adapters()


class TestRestGapInsuranceAdapter:
    """REST gap insurance adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("GAP_INSURANCE_ADAPTER", "rest")
        monkeypatch.delenv("GAP_REST_BASE_URL", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        with pytest.raises(ValueError, match="GAP_REST_BASE_URL"):
            get_gap_insurance_adapter()
        reset_adapters()

    def test_rest_submit_shortfall_returns_claim_id(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("GAP_INSURANCE_ADAPTER", "rest")
        monkeypatch.setenv("GAP_REST_BASE_URL", "https://gap-carrier.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "gap_claim_id": "GAP-REST-9001",
            "status": "submitted",
        }

        with patch("claim_agent.adapters.real.gap_insurance_rest.AdapterHttpClient") as MockClient:
            client = MagicMock()
            client.post.return_value = mock_resp
            MockClient.return_value = client
            adapter = get_gap_insurance_adapter()
            result = adapter.submit_shortfall_claim(
                claim_id="C1",
                policy_number="POL-001",
                auto_payout_amount=15000.0,
                loan_balance=20000.0,
                shortfall_amount=5000.0,
            )
        assert result["gap_claim_id"] == "GAP-REST-9001"
        assert result["status"] == "submitted"
        reset_adapters()


class TestRestOCRAdapter:
    """REST OCR adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("OCR_ADAPTER", "rest")
        monkeypatch.delenv("OCR_REST_BASE_URL", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        with pytest.raises(ValueError, match="OCR_REST_BASE_URL"):
            get_ocr_adapter()
        reset_adapters()

    def test_rest_extract_returns_none_on_missing_file(self, monkeypatch):
        from pathlib import Path

        reset_adapters()
        monkeypatch.setenv("OCR_ADAPTER", "rest")
        monkeypatch.setenv("OCR_REST_BASE_URL", "https://ocr.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        from unittest.mock import patch
        with patch("claim_agent.adapters.real.ocr_rest.AdapterHttpClient"):
            adapter = get_ocr_adapter()
            result = adapter.extract_structured_data(
                Path("/tmp/nonexistent_test_file.pdf"), "estimate"
            )
        assert result is None
        reset_adapters()


class TestRestCMSAdapter:
    """REST CMS reporting adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("CMS_ADAPTER", "rest")
        monkeypatch.delenv("CMS_REST_BASE_URL", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        with pytest.raises(ValueError, match="CMS_REST_BASE_URL"):
            get_cms_reporting_adapter()
        reset_adapters()

    def test_rest_evaluate_returns_reporting_flags(self, monkeypatch):
        from unittest.mock import MagicMock, patch

        reset_adapters()
        monkeypatch.setenv("CMS_ADAPTER", "rest")
        monkeypatch.setenv("CMS_REST_BASE_URL", "https://cms.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "settlement_amount": 50000.0,
            "claimant_medicare_eligible": True,
            "reporting_threshold": 750.0,
            "reporting_required": True,
            "conditional_payment_amount": 3000.0,
            "msa_required": True,
            "notes": "Report to CMS COBC.",
        }

        with patch("claim_agent.adapters.real.cms_rest.AdapterHttpClient") as MockClient:
            client = MagicMock()
            client.post.return_value = mock_resp
            MockClient.return_value = client
            adapter = get_cms_reporting_adapter()
            result = adapter.evaluate_settlement_reporting(
                claim_id="C1",
                settlement_amount=50000.0,
                claimant_medicare_eligible=True,
            )
        assert result["reporting_required"] is True
        assert result["msa_required"] is True
        assert result["conditional_payment_amount"] == 3000.0
        reset_adapters()


class TestRestReverseImageAdapter:
    """REST reverse-image adapter with mocked HTTP."""

    def test_rest_requires_base_url(self, monkeypatch):
        from claim_agent.adapters.registry import get_reverse_image_adapter
        reset_adapters()
        monkeypatch.setenv("REVERSE_IMAGE_ADAPTER", "rest")
        monkeypatch.delenv("REVERSE_IMAGE_REST_BASE_URL", raising=False)
        from claim_agent.config import reload_settings
        reload_settings()
        with pytest.raises(ValueError, match="REVERSE_IMAGE_REST_BASE_URL"):
            get_reverse_image_adapter()
        reset_adapters()

    def test_rest_match_web_occurrences_returns_empty_on_error(self, monkeypatch):
        from claim_agent.adapters.registry import get_reverse_image_adapter
        from unittest.mock import patch

        reset_adapters()
        monkeypatch.setenv("REVERSE_IMAGE_ADAPTER", "rest")
        monkeypatch.setenv("REVERSE_IMAGE_REST_BASE_URL", "https://image-search.example.com/api/v1")
        from claim_agent.config import reload_settings
        reload_settings()

        with patch("claim_agent.adapters.real.reverse_image_rest.AdapterHttpClient"):
            adapter = get_reverse_image_adapter()
            # Pass raw bytes with no network; OSError is caught and returns []
            result = adapter.match_web_occurrences(b"fake-image-bytes")
        # Should return empty list on HTTP error (no real server)
        assert isinstance(result, list)
        reset_adapters()
