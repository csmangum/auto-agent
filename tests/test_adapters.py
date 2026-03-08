"""Tests for the adapter layer: base ABCs, mock implementations, stubs, and registry."""

import os
import uuid

import pytest

from claim_agent.adapters.base import (
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    SIUAdapter,
    ValuationAdapter,
)
from claim_agent.adapters.mock import (
    MockPartsAdapter,
    MockPolicyAdapter,
    MockRepairShopAdapter,
    MockSIUAdapter,
    MockValuationAdapter,
)
from claim_agent.adapters.registry import (
    get_parts_adapter,
    get_policy_adapter,
    get_repair_shop_adapter,
    get_siu_adapter,
    get_valuation_adapter,
    reset_adapters,
)
from claim_agent.adapters.stub import (
    StubPartsAdapter,
    StubPolicyAdapter,
    StubRepairShopAdapter,
    StubSIUAdapter,
    StubValuationAdapter,
)


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


# ---------------------------------------------------------------------------
# Mock adapter unit tests
# ---------------------------------------------------------------------------

class TestMockPolicyAdapter:
    def test_known_policy(self):
        adapter = MockPolicyAdapter()
        result = adapter.get_policy("POL-001")
        assert result is not None
        assert "coverage" in result
        assert "deductible" in result

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

    def test_implements_interface(self):
        assert isinstance(MockSIUAdapter(), SIUAdapter)


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

    def test_stub_backend_via_env(self, monkeypatch):
        reset_adapters()
        monkeypatch.setenv("POLICY_ADAPTER", "stub")
        monkeypatch.setenv("VALUATION_ADAPTER", "stub")
        monkeypatch.setenv("REPAIR_SHOP_ADAPTER", "stub")
        monkeypatch.setenv("PARTS_ADAPTER", "stub")
        monkeypatch.setenv("SIU_ADAPTER", "stub")
        assert isinstance(get_policy_adapter(), StubPolicyAdapter)
        assert isinstance(get_valuation_adapter(), StubValuationAdapter)
        assert isinstance(get_repair_shop_adapter(), StubRepairShopAdapter)
        assert isinstance(get_parts_adapter(), StubPartsAdapter)
        assert isinstance(get_siu_adapter(), StubSIUAdapter)

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
        with pytest.raises(ValueError, match="Unknown POLICY_ADAPTER backend.*rest"):
            get_policy_adapter()
