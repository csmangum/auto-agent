"""Adapter registry -- thread-safe factories driven by environment variables.

Each ``get_*_adapter()`` function returns a singleton selected by the
corresponding ``*_ADAPTER`` env var (default: ``mock``).

Supported values: ``mock``, ``stub``. Unknown values raise ValueError.
"""

import threading
from typing import Any, TypeVar, cast

from claim_agent.adapters.base import (
    ClaimSearchAdapter,
    OCRAdapter,
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    SIUAdapter,
    ValuationAdapter,
)
from claim_agent.config.settings import VALID_ADAPTER_BACKENDS, get_adapter_backend

_lock = threading.Lock()
_cache: dict[str, Any] = {}

T = TypeVar('T')


def _resolve_backend(adapter_name: str) -> str:
    backend = get_adapter_backend(adapter_name)
    if backend not in VALID_ADAPTER_BACKENDS:
        raise ValueError(
            f"Unknown {adapter_name.upper()}_ADAPTER backend: {backend!r}. "
            f"Expected one of: {sorted(VALID_ADAPTER_BACKENDS)}."
        )
    return backend


def _get_or_create_adapter(
    adapter_name: str,
    stub_class: type[T],
    mock_class: type[T],
) -> T:
    if adapter_name in _cache:
        return cast(T, _cache[adapter_name])
    with _lock:
        if adapter_name in _cache:
            return cast(T, _cache[adapter_name])
        backend = _resolve_backend(adapter_name)
        if backend == "stub":
            _cache[adapter_name] = stub_class()
        else:
            _cache[adapter_name] = mock_class()
        return cast(T, _cache[adapter_name])


def get_policy_adapter() -> PolicyAdapter:
    from claim_agent.adapters.stub import StubPolicyAdapter
    from claim_agent.adapters.mock.policy import MockPolicyAdapter
    return _get_or_create_adapter("policy", StubPolicyAdapter, MockPolicyAdapter)


def get_valuation_adapter() -> ValuationAdapter:
    from claim_agent.adapters.stub import StubValuationAdapter
    from claim_agent.adapters.mock.valuation import MockValuationAdapter
    return _get_or_create_adapter("valuation", StubValuationAdapter, MockValuationAdapter)


def get_repair_shop_adapter() -> RepairShopAdapter:
    from claim_agent.adapters.stub import StubRepairShopAdapter
    from claim_agent.adapters.mock.repair_shop import MockRepairShopAdapter
    return _get_or_create_adapter("repair_shop", StubRepairShopAdapter, MockRepairShopAdapter)


def get_parts_adapter() -> PartsAdapter:
    from claim_agent.adapters.stub import StubPartsAdapter
    from claim_agent.adapters.mock.parts import MockPartsAdapter
    return _get_or_create_adapter("parts", StubPartsAdapter, MockPartsAdapter)


def get_siu_adapter() -> SIUAdapter:
    from claim_agent.adapters.stub import StubSIUAdapter
    from claim_agent.adapters.mock.siu import MockSIUAdapter
    return _get_or_create_adapter("siu", StubSIUAdapter, MockSIUAdapter)


def get_claim_search_adapter() -> ClaimSearchAdapter:
    from claim_agent.adapters.stub import StubClaimSearchAdapter
    from claim_agent.adapters.mock.claim_search import MockClaimSearchAdapter
    return _get_or_create_adapter("claim_search", StubClaimSearchAdapter, MockClaimSearchAdapter)


def get_ocr_adapter() -> OCRAdapter:
    from claim_agent.adapters.stub import StubOCRAdapter
    from claim_agent.adapters.mock.ocr import MockOCRAdapter
    return _get_or_create_adapter("ocr", StubOCRAdapter, MockOCRAdapter)


def reset_adapters() -> None:
    """Clear cached singletons (useful in tests)."""
    with _lock:
        _cache.clear()
