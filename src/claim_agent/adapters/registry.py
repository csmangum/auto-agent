"""Adapter registry -- thread-safe factories driven by environment variables.

Each ``get_*_adapter()`` function returns a singleton selected by the
corresponding ``*_ADAPTER`` env var (default: ``mock``).

Supported values: ``mock``, ``stub``, ``rest`` (policy and fraud_reporting). Valuation also supports
``ccc``, ``mitchell``, ``audatex`` with ``VALUATION_REST_*`` settings.
``nmvtis``, ``gap_insurance``, and ``cms`` support ``mock`` and ``stub`` only. Unknown values raise ValueError.
"""

import threading
from typing import Any, Callable, TypeVar, cast

from claim_agent.adapters.base import (
    CMSReportingAdapter,
    ClaimSearchAdapter,
    FraudReportingAdapter,
    GapInsuranceAdapter,
    NMVTISAdapter,
    OCRAdapter,
    PartsAdapter,
    PolicyAdapter,
    RepairShopAdapter,
    SIUAdapter,
    ValuationAdapter,
)
from claim_agent.config.settings import VALID_ADAPTER_BACKENDS, get_adapter_backend
from claim_agent.config.settings_model import (
    REST_CAPABLE_ADAPTERS,
    VALUATION_PROVIDER_BACKENDS,
)

_lock = threading.Lock()
_cache: dict[str, Any] = {}

T = TypeVar('T')


def _resolve_backend(adapter_name: str) -> str:
    backend = get_adapter_backend(adapter_name)
    if adapter_name == "valuation":
        allowed = (VALID_ADAPTER_BACKENDS - {"rest"}) | VALUATION_PROVIDER_BACKENDS
    else:
        allowed = VALID_ADAPTER_BACKENDS
    if backend not in allowed:
        if adapter_name == "valuation" and backend == "rest":
            raise ValueError(
                f"{adapter_name.upper()}_ADAPTER=rest is not supported. "
                f"Use ccc, mitchell, or audatex with VALUATION_REST_BASE_URL "
                f"(and optional VALUATION_REST_PATH_TEMPLATE / VALUATION_REST_RESPONSE_KEY)."
            )
        raise ValueError(
            f"Unknown {adapter_name.upper()}_ADAPTER backend: {backend!r}. "
            f"Expected one of: {sorted(allowed)}."
        )
    if backend == "rest" and adapter_name not in REST_CAPABLE_ADAPTERS:
        raise ValueError(
            f"{adapter_name.upper()}_ADAPTER=rest is not supported. "
            f"REST backend is only available for: {sorted(REST_CAPABLE_ADAPTERS)}."
        )
    return backend


def _get_or_create_adapter(
    adapter_name: str,
    stub_class: type[T],
    mock_class: type[T],
    rest_factory: Callable[[], T] | None = None,
) -> T:
    if adapter_name in _cache:
        return cast(T, _cache[adapter_name])
    with _lock:
        if adapter_name in _cache:
            return cast(T, _cache[adapter_name])
        backend = _resolve_backend(adapter_name)
        if backend == "rest":
            if rest_factory is None:
                raise ValueError(
                    f"No REST implementation for {adapter_name} adapter. "
                    f"REST backend is only supported for policy adapter."
                )
            _cache[adapter_name] = rest_factory()
        elif backend == "stub":
            _cache[adapter_name] = stub_class()
        else:
            _cache[adapter_name] = mock_class()
        return cast(T, _cache[adapter_name])


def _policy_rest_factory() -> PolicyAdapter:
    from claim_agent.adapters.real.policy_rest import RestPolicyAdapter
    from claim_agent.config import get_settings
    cfg = get_settings().policy_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "POLICY_REST_BASE_URL is required when POLICY_ADAPTER=rest. "
            "Set POLICY_REST_BASE_URL to your PAS API base URL."
        )
    return RestPolicyAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value,
        path_template=cfg.path_template or None,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
    )


def get_policy_adapter() -> PolicyAdapter:
    from claim_agent.adapters.stub import StubPolicyAdapter
    from claim_agent.adapters.mock.policy import MockPolicyAdapter
    return _get_or_create_adapter(
        "policy",
        StubPolicyAdapter,
        MockPolicyAdapter,
        rest_factory=_policy_rest_factory,
    )


def get_valuation_adapter() -> ValuationAdapter:
    from claim_agent.adapters.mock.valuation import MockValuationAdapter
    from claim_agent.adapters.real.valuation_rest import create_valuation_rest_adapter
    from claim_agent.adapters.stub import StubValuationAdapter

    key = "valuation"
    if key in _cache:
        return cast(ValuationAdapter, _cache[key])
    with _lock:
        if key in _cache:
            return cast(ValuationAdapter, _cache[key])
        backend = _resolve_backend(key)
        if backend in VALUATION_PROVIDER_BACKENDS:
            _cache[key] = create_valuation_rest_adapter(backend)
        elif backend == "stub":
            _cache[key] = StubValuationAdapter()
        elif backend == "mock":
            _cache[key] = MockValuationAdapter()
        return cast(ValuationAdapter, _cache[key])


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


def get_nmvtis_adapter() -> NMVTISAdapter:
    from claim_agent.adapters.mock.nmvtis import MockNMVTISAdapter
    from claim_agent.adapters.stub import StubNMVTISAdapter
    return _get_or_create_adapter(
        "nmvtis",
        StubNMVTISAdapter,
        MockNMVTISAdapter,
    )


def get_gap_insurance_adapter() -> GapInsuranceAdapter:
    from claim_agent.adapters.mock.gap_insurance import MockGapInsuranceAdapter
    from claim_agent.adapters.stub import StubGapInsuranceAdapter
    return _get_or_create_adapter(
        "gap_insurance",
        StubGapInsuranceAdapter,
        MockGapInsuranceAdapter,
    )


def get_cms_reporting_adapter() -> CMSReportingAdapter:
    from claim_agent.adapters.mock.cms_reporting import MockCMSReportingAdapter
    from claim_agent.adapters.stub import StubCMSReportingAdapter
    return _get_or_create_adapter(
        "cms",
        StubCMSReportingAdapter,
        MockCMSReportingAdapter,
    )


def _fraud_reporting_rest_factory() -> FraudReportingAdapter:
    from claim_agent.adapters.real.fraud_reporting_rest import create_rest_fraud_reporting_adapter
    return create_rest_fraud_reporting_adapter()


def get_fraud_reporting_adapter() -> FraudReportingAdapter:
    from claim_agent.adapters.mock.fraud_reporting import MockFraudReportingAdapter
    from claim_agent.adapters.stub_fraud_reporting import StubFraudReportingAdapter
    return _get_or_create_adapter(
        "fraud_reporting",
        StubFraudReportingAdapter,
        MockFraudReportingAdapter,
        rest_factory=_fraud_reporting_rest_factory,
    )


def reset_adapters() -> None:
    """Clear cached singletons (useful in tests)."""
    with _lock:
        _cache.clear()
