"""REST NMVTIS adapter for submitting total-loss / salvage reports to the federal NMVTIS gateway.

Production NMVTIS integrations connect to the DOJ/AAMVA-designated data provider
(49 U.S.C. 30502; 28 CFR Part 25). This adapter wraps a REST gateway that handles
the NMVTIS submission protocol.

Configure via environment variables:

- NMVTIS_REST_BASE_URL: Base URL (e.g. https://nmvtis-gateway.example.com/api/v1)
- NMVTIS_REST_AUTH_HEADER: Auth header name (default: Authorization)
- NMVTIS_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- NMVTIS_REST_REPORT_PATH: Path for submitting reports (default: /nmvtis/reports)
- NMVTIS_REST_RESPONSE_KEY: Optional JSON key wrapping the payload (e.g. data)
- NMVTIS_REST_TIMEOUT: Request timeout in seconds (default: 15)
"""

from __future__ import annotations

import logging
from typing import Any

from claim_agent.adapters.base import NMVTISAdapter
from claim_agent.adapters.http_client import (
    AdapterHttpClient,
    CircuitOpenError,
    extract_response_envelope,
    safe_adapter_json_dict,
)

logger = logging.getLogger(__name__)


class RestNMVTISAdapter(NMVTISAdapter):
    """NMVTIS adapter backed by a REST gateway API.

    Expected API contract:

    * ``POST {report_path}`` with a JSON body containing ``claim_id``, ``vin``,
      ``vehicle_year``, ``make``, ``model``, ``loss_type``, ``trigger_event``, and
      optionally ``dmv_reference`` → 200/201 JSON with ``nmvtis_reference`` and ``status``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        report_path: str = "/nmvtis/reports",
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
            adapter_name="nmvtis",
        )
        self._report_path = report_path
        self._response_key = (response_key or "").strip() or None

    def submit_total_loss_report(
        self,
        *,
        claim_id: str,
        vin: str,
        vehicle_year: int,
        make: str,
        model: str,
        loss_type: str,
        trigger_event: str,
        dmv_reference: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "claim_id": claim_id,
            "vin": vin,
            "vehicle_year": vehicle_year,
            "make": make,
            "model": model,
            "loss_type": loss_type,
            "trigger_event": trigger_event,
        }
        if dmv_reference is not None:
            body["dmv_reference"] = dmv_reference

        try:
            resp = self._client.post(self._report_path, json=body)
        except CircuitOpenError:
            logger.warning("NMVTIS adapter circuit breaker open on submit_total_loss_report")
            raise ValueError("NMVTIS REST unavailable: circuit breaker open") from None
        parsed = safe_adapter_json_dict(resp, log_label="nmvtis_rest")
        if parsed is None:
            raise ValueError("NMVTIS REST API returned invalid or non-object JSON")
        data = extract_response_envelope(parsed, self._response_key)
        if not isinstance(data, dict):
            raise ValueError(
                f"NMVTIS REST API returned unexpected response type: {type(data).__name__}"
            )
        # Normalise response to canonical contract
        ref = str(data.get("nmvtis_reference") or data.get("reference") or data.get("id") or "")
        status = str(data.get("status") or "pending")
        result: dict[str, Any] = {"nmvtis_reference": ref, "status": status}
        if "message" in data:
            result["message"] = data["message"]
        return result

    def health_check(self) -> tuple[bool, str]:
        """Probe the NMVTIS gateway for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_nmvtis_adapter() -> RestNMVTISAdapter:
    """Build a REST NMVTIS adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().nmvtis_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "NMVTIS_REST_BASE_URL is required when NMVTIS_ADAPTER=rest. "
            "Set NMVTIS_REST_BASE_URL to your NMVTIS gateway API base URL."
        )
    return RestNMVTISAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value.get_secret_value(),
        report_path=cfg.report_path,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
    )
