"""REST gap-insurance carrier adapter for coordinating loan/lease shortfall claims.

Configure via environment variables:

- GAP_REST_BASE_URL: Base URL (e.g. https://gap-carrier.example.com/api/v1)
- GAP_REST_AUTH_HEADER: Auth header name (default: Authorization)
- GAP_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- GAP_REST_SUBMIT_PATH: Path for submitting shortfall claims (default: /gap/claims)
- GAP_REST_STATUS_PATH_TEMPLATE: Path template for polling claim status; {gap_claim_id}
  placeholder (default: /gap/claims/{gap_claim_id})
- GAP_REST_RESPONSE_KEY: Optional JSON key wrapping the payload (e.g. data)
- GAP_REST_TIMEOUT: Request timeout in seconds (default: 15)
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from claim_agent.adapters.base import GapInsuranceAdapter
from claim_agent.adapters.http_client import (
    AdapterHttpClient,
    CircuitOpenError,
    extract_response_envelope,
    safe_adapter_json_dict,
)

logger = logging.getLogger(__name__)


class RestGapInsuranceAdapter(GapInsuranceAdapter):
    """Gap-insurance adapter backed by a real carrier REST API.

    Expected API contract:

    * ``POST {submit_path}`` with JSON ``{claim_id, policy_number, auto_payout_amount,
      loan_balance, shortfall_amount, vin}`` → 200/201 JSON with ``gap_claim_id`` and
      ``status``.
    * ``GET {status_path_template}`` (with ``{gap_claim_id}`` substituted) → 200 JSON for
      current status, 404 when not found.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        submit_path: str = "/gap/claims",
        status_path_template: str = "/gap/claims/{gap_claim_id}",
        response_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._client = AdapterHttpClient(
            base_url=base_url,
            auth_header=auth_header,
            auth_value=auth_value,
            timeout=timeout,
        )
        self._submit_path = submit_path
        self._status_path_template = status_path_template.strip()
        self._response_key = (response_key or "").strip() or None

    def submit_shortfall_claim(
        self,
        *,
        claim_id: str,
        policy_number: str,
        auto_payout_amount: float,
        loan_balance: float,
        shortfall_amount: float,
        vin: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "claim_id": claim_id,
            "policy_number": policy_number,
            "auto_payout_amount": auto_payout_amount,
            "loan_balance": loan_balance,
            "shortfall_amount": shortfall_amount,
        }
        if vin is not None:
            body["vin"] = vin

        try:
            resp = self._client.post(self._submit_path, json=body)
        except CircuitOpenError:
            logger.warning("Gap insurance adapter circuit breaker open on submit_shortfall_claim")
            raise ValueError("Gap insurance REST unavailable: circuit breaker open") from None
        parsed = safe_adapter_json_dict(resp, log_label="gap_insurance_rest")
        if parsed is None:
            raise ValueError("Gap insurance REST API returned invalid or non-object JSON")
        data = extract_response_envelope(parsed, self._response_key)
        if not isinstance(data, dict):
            raise ValueError(
                f"Gap insurance REST API returned unexpected response type: {type(data).__name__}"
            )
        # Normalise to canonical contract
        gap_claim_id = str(
            data.get("gap_claim_id") or data.get("id") or data.get("claimId") or ""
        )
        status = str(data.get("status") or "submitted")
        result: dict[str, Any] = {"gap_claim_id": gap_claim_id, "status": status}
        for key in ("approved_amount", "denial_reason", "remaining_shortfall_after_gap", "message"):
            if key in data:
                result[key] = data[key]
        return result

    def get_claim_status(self, gap_claim_id: str) -> dict[str, Any] | None:
        encoded = quote(gap_claim_id, safe="")
        path = self._status_path_template.replace("{gap_claim_id}", encoded)
        try:
            resp = self._client.get(path)
        except CircuitOpenError:
            logger.warning("Gap insurance adapter circuit breaker open; returning None")
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        parsed = safe_adapter_json_dict(resp, log_label="gap_insurance_rest")
        if parsed is None:
            return None
        data = extract_response_envelope(parsed, self._response_key)
        return data if isinstance(data, dict) else None

    def health_check(self) -> tuple[bool, str]:
        """Probe the gap carrier API for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_gap_insurance_adapter() -> RestGapInsuranceAdapter:
    """Build a REST GapInsurance adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().gap_insurance_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "GAP_REST_BASE_URL is required when GAP_INSURANCE_ADAPTER=rest. "
            "Set GAP_REST_BASE_URL to your gap carrier API base URL."
        )
    return RestGapInsuranceAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value,
        submit_path=cfg.submit_path,
        status_path_template=cfg.status_path_template,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
    )
