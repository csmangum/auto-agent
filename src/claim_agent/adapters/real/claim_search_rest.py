"""REST ClaimSearch adapter for NICB/ISO-style cross-carrier claim search."""

from __future__ import annotations

from typing import Any

from claim_agent.adapters.base import ClaimSearchAdapter
from claim_agent.adapters.http_client import AdapterHttpClient
from claim_agent.config import get_settings


def _to_string(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    s = str(value).strip()
    return s if s else fallback


class RestClaimSearchAdapter(ClaimSearchAdapter):
    """HTTP-backed ClaimSearch adapter for NICB/ISO-style cross-carrier lookups.

    Sends a POST request to the configured ``search_path`` with a JSON body
    containing ``vin``, ``claimant_name``, ``date_from``, and ``date_to``
    (all optional).  The response is normalised to the ``list[dict]`` format
    expected by ``cross_reference_fraud_indicators_impl``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        search_path: str = "/claims/search",
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
        self._search_path = search_path
        self._response_key = (response_key or "").strip() or None

    def _extract_results(self, raw: Any) -> list[Any]:
        """Extract the list of claim matches from the API response."""
        if isinstance(raw, list):
            return raw
        if not isinstance(raw, dict):
            return []
        if self._response_key:
            nested = raw.get(self._response_key)
            return nested if isinstance(nested, list) else []
        # Try common envelope keys before returning empty
        for key in ("results", "matches", "claims", "data"):
            if key in raw:
                val = raw[key]
                if isinstance(val, list):
                    return val
        return []

    def _normalize_match(
        self,
        raw: Any,
        vin: str | None,
        claimant_name: str | None,
    ) -> dict[str, Any]:
        """Normalise a single API result to the canonical match dict."""
        if not isinstance(raw, dict):
            return {}
        return {
            "external_claim_id": _to_string(
                raw.get("external_claim_id") or raw.get("claim_id") or raw.get("id")
            ),
            "source": _to_string(raw.get("source") or raw.get("provider"), "unknown"),
            "vin": _to_string(raw.get("vin"), vin or ""),
            "claimant_name": _to_string(
                raw.get("claimant_name") or raw.get("name"), claimant_name or ""
            ),
            "status": _to_string(raw.get("status"), "unknown"),
        }

    def search_claims(
        self,
        *,
        vin: str | None = None,
        claimant_name: str | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {}
        if vin:
            body["vin"] = vin
        if claimant_name:
            body["claimant_name"] = claimant_name
        if date_range:
            body["date_from"] = date_range[0]
            body["date_to"] = date_range[1]
        resp = self._client.post(self._search_path, json=body)
        raw = resp.json()
        items = self._extract_results(raw)
        return [
            m
            for m in (self._normalize_match(item, vin, claimant_name) for item in items)
            if m
        ]

    def health_check(self) -> tuple[bool, str]:
        """Probe the ClaimSearch REST API for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_claim_search_adapter() -> RestClaimSearchAdapter:
    """Build a REST ClaimSearch adapter from environment settings."""
    cfg = get_settings().claim_search_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "CLAIM_SEARCH_REST_BASE_URL is required when CLAIM_SEARCH_ADAPTER=rest. "
            "Set CLAIM_SEARCH_REST_BASE_URL to your ClaimSearch API base URL."
        )
    return RestClaimSearchAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value.get_secret_value(),
        search_path=cfg.search_path,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
    )
