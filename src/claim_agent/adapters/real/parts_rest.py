"""REST parts-catalog adapter for querying an external parts management API.

Configure via environment variables:

- PARTS_REST_BASE_URL: Base URL (e.g. https://parts.example.com/api/v1)
- PARTS_REST_AUTH_HEADER: Auth header name (default: Authorization)
- PARTS_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- PARTS_REST_CATALOG_PATH: Path for the parts catalog (default: /parts/catalog)
- PARTS_REST_RESPONSE_KEY: Optional JSON key wrapping the payload (e.g. data)
- PARTS_REST_TIMEOUT: Request timeout in seconds (default: 15)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from claim_agent.adapters.base import PartsAdapter
from claim_agent.adapters.http_client import (
    AdapterHttpClient,
    CircuitOpenError,
    extract_response_envelope,
)

logger = logging.getLogger(__name__)


class RestPartsAdapter(PartsAdapter):
    """Parts-catalog adapter backed by a real REST API.

    Expected API contract:

    * ``GET {catalog_path}`` → 200 JSON: a list or dict of parts entries.

    Responses may be wrapped in an optional envelope key (``response_key``).
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        catalog_path: str = "/parts/catalog",
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
        self._catalog_path = catalog_path
        self._response_key = (response_key or "").strip() or None

    def _to_catalog_dict(self, raw: Any) -> dict[str, dict[str, Any]]:
        """Normalize list or dict API responses to ``{part_id: part_data}`` format."""
        if isinstance(raw, dict):
            return {str(k): v for k, v in raw.items() if isinstance(v, dict)}
        if isinstance(raw, list):
            result: dict[str, dict[str, Any]] = {}
            for item in raw:
                if isinstance(item, dict):
                    pid = str(
                        item.get("part_id") or item.get("id") or item.get("partNumber") or ""
                    )
                    if pid:
                        result[pid] = item
            return result
        return {}

    def get_catalog(self) -> dict[str, dict[str, Any]]:
        try:
            resp = self._client.get(self._catalog_path)
        except CircuitOpenError:
            logger.warning("Parts adapter circuit breaker open; returning empty catalog")
            return {}
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return {}
            raise
        raw = extract_response_envelope(resp.json(), self._response_key)
        return self._to_catalog_dict(raw)

    def health_check(self) -> tuple[bool, str]:
        """Probe the parts API for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_parts_adapter() -> RestPartsAdapter:
    """Build a REST Parts adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().parts_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "PARTS_REST_BASE_URL is required when PARTS_ADAPTER=rest. "
            "Set PARTS_REST_BASE_URL to your parts management API base URL."
        )
    return RestPartsAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value.get_secret_value(),
        catalog_path=cfg.catalog_path,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
    )
