"""Adapter registry -- thread-safe factories driven by environment variables.

Each ``get_*_adapter()`` function returns a singleton selected by the
corresponding ``*_ADAPTER`` env var (default: ``mock``).

Supported values: ``mock``, ``stub``. Unknown values raise ValueError.
"""

import threading

from claim_agent.adapters.base import (
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    SIUAdapter,
    ValuationAdapter,
)
from claim_agent.config.settings import VALID_ADAPTER_BACKENDS, get_adapter_backend

_lock = threading.Lock()

_policy_adapter: PolicyAdapter | None = None
_valuation_adapter: ValuationAdapter | None = None
_repair_shop_adapter: RepairShopAdapter | None = None
_parts_adapter: PartsAdapter | None = None
_siu_adapter: SIUAdapter | None = None


def _resolve_backend(adapter_name: str) -> str:
    backend = get_adapter_backend(adapter_name)
    if backend not in VALID_ADAPTER_BACKENDS:
        raise ValueError(
            f"Unknown {adapter_name.upper()}_ADAPTER backend: {backend!r}. "
            f"Expected one of: {sorted(VALID_ADAPTER_BACKENDS)}."
        )
    return backend


def get_policy_adapter() -> PolicyAdapter:
    global _policy_adapter
    if _policy_adapter is not None:
        return _policy_adapter
    with _lock:
        if _policy_adapter is not None:
            return _policy_adapter
        backend = _resolve_backend("policy")
        if backend == "stub":
            from claim_agent.adapters.stub import StubPolicyAdapter
            _policy_adapter = StubPolicyAdapter()
        else:
            from claim_agent.adapters.mock.policy import MockPolicyAdapter
            _policy_adapter = MockPolicyAdapter()
        return _policy_adapter


def get_valuation_adapter() -> ValuationAdapter:
    global _valuation_adapter
    if _valuation_adapter is not None:
        return _valuation_adapter
    with _lock:
        if _valuation_adapter is not None:
            return _valuation_adapter
        backend = _resolve_backend("valuation")
        if backend == "stub":
            from claim_agent.adapters.stub import StubValuationAdapter
            _valuation_adapter = StubValuationAdapter()
        else:
            from claim_agent.adapters.mock.valuation import MockValuationAdapter
            _valuation_adapter = MockValuationAdapter()
        return _valuation_adapter


def get_repair_shop_adapter() -> RepairShopAdapter:
    global _repair_shop_adapter
    if _repair_shop_adapter is not None:
        return _repair_shop_adapter
    with _lock:
        if _repair_shop_adapter is not None:
            return _repair_shop_adapter
        backend = _resolve_backend("repair_shop")
        if backend == "stub":
            from claim_agent.adapters.stub import StubRepairShopAdapter
            _repair_shop_adapter = StubRepairShopAdapter()
        else:
            from claim_agent.adapters.mock.repair_shop import MockRepairShopAdapter
            _repair_shop_adapter = MockRepairShopAdapter()
        return _repair_shop_adapter


def get_parts_adapter() -> PartsAdapter:
    global _parts_adapter
    if _parts_adapter is not None:
        return _parts_adapter
    with _lock:
        if _parts_adapter is not None:
            return _parts_adapter
        backend = _resolve_backend("parts")
        if backend == "stub":
            from claim_agent.adapters.stub import StubPartsAdapter
            _parts_adapter = StubPartsAdapter()
        else:
            from claim_agent.adapters.mock.parts import MockPartsAdapter
            _parts_adapter = MockPartsAdapter()
        return _parts_adapter


def get_siu_adapter() -> SIUAdapter:
    global _siu_adapter
    if _siu_adapter is not None:
        return _siu_adapter
    with _lock:
        if _siu_adapter is not None:
            return _siu_adapter
        backend = _resolve_backend("siu")
        if backend == "stub":
            from claim_agent.adapters.stub import StubSIUAdapter
            _siu_adapter = StubSIUAdapter()
        else:
            from claim_agent.adapters.mock.siu import MockSIUAdapter
            _siu_adapter = MockSIUAdapter()
        return _siu_adapter


def reset_adapters() -> None:
    """Clear cached singletons (useful in tests)."""
    global _policy_adapter, _valuation_adapter, _repair_shop_adapter
    global _parts_adapter, _siu_adapter
    with _lock:
        _policy_adapter = None
        _valuation_adapter = None
        _repair_shop_adapter = None
        _parts_adapter = None
        _siu_adapter = None
