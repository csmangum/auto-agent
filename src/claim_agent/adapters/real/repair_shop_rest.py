"""REST repair-shop adapter for direct network queries against a shop-management API.

Configure via environment variables:

- REPAIR_SHOP_REST_BASE_URL: Base URL (e.g. https://shops.example.com/api/v1)
- REPAIR_SHOP_REST_AUTH_HEADER: Auth header name (default: Authorization)
- REPAIR_SHOP_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- REPAIR_SHOP_REST_SHOPS_PATH: Path for listing all shops (default: /shops)
- REPAIR_SHOP_REST_SHOP_PATH_TEMPLATE: Path template for a single shop, {shop_id} placeholder
  (default: /shops/{shop_id})
- REPAIR_SHOP_REST_LABOR_PATH: Path for labor operations catalog (default: /shops/labor-operations)
- REPAIR_SHOP_REST_RESPONSE_KEY: Optional JSON key wrapping the payload (e.g. data)
- REPAIR_SHOP_REST_TIMEOUT: Request timeout in seconds (default: 15)
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from claim_agent.adapters.base import RepairShopAdapter
from claim_agent.adapters.http_client import (
    AdapterHttpClient,
    CircuitOpenError,
    extract_response_envelope,
)

logger = logging.getLogger(__name__)


class RestRepairShopAdapter(RepairShopAdapter):
    """Repair-shop adapter backed by a real REST API.

    Expected API contract:

    * ``GET {shops_path}`` → 200 JSON: a list or dict of shops.
    * ``GET {shop_path_template}`` (with ``{shop_id}`` substituted) → 200 JSON for a
      single shop, 404 when not found.
    * ``GET {labor_path}`` → 200 JSON: a list or dict of labor operations.

    All responses may be wrapped in an optional envelope key (``response_key``).
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        shops_path: str = "/shops",
        shop_path_template: str = "/shops/{shop_id}",
        labor_path: str = "/shops/labor-operations",
        response_key: str | None = None,
        timeout: float = 15.0,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 60.0,
    ) -> None:
        self._client = AdapterHttpClient(
            base_url=base_url,
            auth_header=auth_header,
            auth_value=auth_value,
            timeout=timeout,
            circuit_failure_threshold=circuit_failure_threshold,
            circuit_recovery_timeout=circuit_recovery_timeout,
        )
        self._shops_path = shops_path
        self._shop_path_template = shop_path_template.strip()
        self._labor_path = labor_path
        self._response_key = (response_key or "").strip() or None

    def _to_shop_dict(self, raw: Any) -> dict[str, dict[str, Any]]:
        """Normalize list or dict API responses to ``{shop_id: shop_data}`` format."""
        if isinstance(raw, dict):
            return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        if isinstance(raw, list):
            result: dict[str, dict[str, Any]] = {}
            for item in raw:
                if isinstance(item, dict):
                    sid = str(
                        item.get("shop_id") or item.get("id") or item.get("shopId") or ""
                    )
                    if sid:
                        result[sid] = item
            return result
        return {}

    def _to_catalog_dict(self, raw: Any) -> dict[str, dict[str, Any]]:
        """Normalize list or dict API responses to ``{op_id: op_data}`` format."""
        if isinstance(raw, dict):
            return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        if isinstance(raw, list):
            result: dict[str, dict[str, Any]] = {}
            for item in raw:
                if isinstance(item, dict):
                    oid = str(
                        item.get("op_id") or item.get("id") or item.get("operation_id") or ""
                    )
                    if oid:
                        result[oid] = item
            return result
        return {}

    def get_shops(self) -> dict[str, dict[str, Any]]:
        try:
            resp = self._client.get(self._shops_path)
        except CircuitOpenError:
            logger.warning("RepairShop adapter circuit breaker open; returning empty shops")
            return {}
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return {}
            raise
        raw = extract_response_envelope(resp.json(), self._response_key)
        return self._to_shop_dict(raw)

    def get_shop(self, shop_id: str) -> dict[str, Any] | None:
        encoded = quote(shop_id, safe="")
        path = self._shop_path_template.replace("{shop_id}", encoded)
        try:
            resp = self._client.get(path)
        except CircuitOpenError:
            logger.warning("RepairShop adapter circuit breaker open; returning None")
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        raw = extract_response_envelope(resp.json(), self._response_key)
        return raw if isinstance(raw, dict) else None

    def get_labor_operations(self) -> dict[str, dict[str, Any]]:
        try:
            resp = self._client.get(self._labor_path)
        except CircuitOpenError:
            logger.warning("RepairShop adapter circuit breaker open; returning empty labor ops")
            return {}
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return {}
            raise
        raw = extract_response_envelope(resp.json(), self._response_key)
        return self._to_catalog_dict(raw)

    def health_check(self) -> tuple[bool, str]:
        """Probe the shop API for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_repair_shop_adapter() -> RestRepairShopAdapter:
    """Build a REST RepairShop adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().repair_shop_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "REPAIR_SHOP_REST_BASE_URL is required when REPAIR_SHOP_ADAPTER=rest. "
            "Set REPAIR_SHOP_REST_BASE_URL to your shop management API base URL."
        )
    return RestRepairShopAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value,
        shops_path=cfg.shops_path,
        shop_path_template=cfg.shop_path_template,
        labor_path=cfg.labor_path,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
    )
