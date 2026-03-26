"""REST CMS / Medicare reporting adapter (MMSEA Section 111) for connecting to an external
CMS COBC reporting gateway.

Configure via environment variables:

- CMS_REST_BASE_URL: Base URL (e.g. https://cms-reporting.example.com/api/v1)
- CMS_REST_AUTH_HEADER: Auth header name (default: Authorization)
- CMS_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- CMS_REST_EVALUATE_PATH: Path for settlement reporting evaluation (default: /cms/evaluate)
- CMS_REST_RESPONSE_KEY: Optional JSON key wrapping the payload (e.g. data)
- CMS_REST_TIMEOUT: Request timeout in seconds (default: 15)
"""

from __future__ import annotations

import logging
from typing import Any

from claim_agent.adapters.base import CMSReportingAdapter
from claim_agent.adapters.http_client import (
    AdapterHttpClient,
    CircuitOpenError,
    extract_response_envelope,
    safe_adapter_json_dict,
)

logger = logging.getLogger(__name__)

# Default reporting threshold for MMSEA Section 111 (matches mock default)
_DEFAULT_REPORTING_THRESHOLD = 750.0


class RestCMSReportingAdapter(CMSReportingAdapter):
    """CMS/Medicare reporting adapter backed by a real REST gateway.

    Expected API contract:

    * ``POST {evaluate_path}`` with JSON ``{claim_id, settlement_amount,
      claimant_medicare_eligible}`` → 200 JSON with the canonical reporting flags.

    The response is expected to match the keys defined in
    ``CMSReportingAdapter.evaluate_settlement_reporting``.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        evaluate_path: str = "/cms/evaluate",
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
        self._evaluate_path = evaluate_path
        self._response_key = (response_key or "").strip() or None

    def evaluate_settlement_reporting(
        self,
        *,
        claim_id: str,
        settlement_amount: float,
        claimant_medicare_eligible: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "claim_id": claim_id,
            "settlement_amount": settlement_amount,
            "claimant_medicare_eligible": claimant_medicare_eligible,
        }
        try:
            resp = self._client.post(self._evaluate_path, json=body)
        except CircuitOpenError:
            logger.warning("CMS adapter circuit breaker open; returning conservative defaults")
            return {
                "settlement_amount": settlement_amount,
                "claimant_medicare_eligible": claimant_medicare_eligible,
                "reporting_threshold": _DEFAULT_REPORTING_THRESHOLD,
                "reporting_required": False,
                "conditional_payment_amount": None,
                "msa_required": False,
                "notes": "",
            }
        parsed = safe_adapter_json_dict(resp, log_label="cms_rest")
        if parsed is None:
            raise ValueError("CMS REST API returned invalid or non-object JSON")
        data = extract_response_envelope(parsed, self._response_key)
        if not isinstance(data, dict):
            raise ValueError(
                f"CMS REST API returned unexpected response type: {type(data).__name__}"
            )
        # Ensure all required keys are present; fall back to safe defaults if absent
        result: dict[str, Any] = {
            "settlement_amount": data.get("settlement_amount", settlement_amount),
            "claimant_medicare_eligible": data.get(
                "claimant_medicare_eligible", claimant_medicare_eligible
            ),
            "reporting_threshold": data.get("reporting_threshold", _DEFAULT_REPORTING_THRESHOLD),
            "reporting_required": bool(data.get("reporting_required", False)),
            "conditional_payment_amount": data.get("conditional_payment_amount"),
            "msa_required": bool(data.get("msa_required", False)),
            "notes": str(data.get("notes", "")),
        }
        return result

    def health_check(self) -> tuple[bool, str]:
        """Probe the CMS gateway for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_cms_reporting_adapter() -> RestCMSReportingAdapter:
    """Build a REST CMS reporting adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().cms_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "CMS_REST_BASE_URL is required when CMS_ADAPTER=rest. "
            "Set CMS_REST_BASE_URL to your CMS reporting gateway base URL."
        )
    return RestCMSReportingAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value,
        evaluate_path=cfg.evaluate_path,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
    )
