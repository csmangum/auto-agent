"""REST medical records adapter for connecting to an HIE or provider portal.

Configure via environment variables:

- MEDICAL_RECORDS_REST_BASE_URL: Base URL (e.g. https://hie.example.com/api/v1)
- MEDICAL_RECORDS_REST_AUTH_HEADER: Auth header name (default: Authorization)
- MEDICAL_RECORDS_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- MEDICAL_RECORDS_REST_QUERY_PATH: Path for records query endpoint (default: /medical-records/query)
- MEDICAL_RECORDS_REST_RESPONSE_KEY: Optional JSON key wrapping the payload (e.g. data)
- MEDICAL_RECORDS_REST_TIMEOUT: Request timeout in seconds (default: 30)

Privacy note: all data returned by this adapter is PHI.  Ensure HIPAA minimum-necessary
standards are applied, all access is logged, and transmission is encrypted (TLS 1.2+).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from claim_agent.adapters.base import MedicalRecordsAdapter
from claim_agent.adapters.http_client import (
    AdapterHttpClient,
    CircuitOpenError,
    extract_response_envelope,
    safe_adapter_json_dict,
)

logger = logging.getLogger(__name__)


class RestMedicalRecordsAdapter(MedicalRecordsAdapter):
    """Medical records adapter backed by a real REST HIE or provider portal API.

    Expected API contract:

    * ``POST {query_path}`` with JSON ``{claim_id, claimant_id, date_range?}``
      → 200 JSON with the canonical medical records structure, or 404 if no
      records are found for the given claimant / claim combination.

    The response must contain (or be unwrapped via *response_key* to contain):

    * ``claim_id`` (str)
    * ``claimant_id`` (str)
    * ``records`` (list[dict]): each entry has ``provider``, ``date_of_service``,
      ``diagnosis``, ``charges`` (float), ``treatment``.
    * ``total_charges`` (float)
    * ``treatment_summary`` (str)
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        query_path: str = "/medical-records/query",
        response_key: str | None = None,
        timeout: float = 30.0,
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
            adapter_name="medical_records",
        )
        self._query_path = query_path
        self._response_key = (response_key or "").strip() or None

    def query_medical_records(
        self,
        claim_id: str,
        claimant_id: str = "",
        *,
        date_range: tuple[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """POST to the HIE/provider portal and return normalized medical records.

        Returns ``None`` if the provider returns 404 (no records found) or if
        the circuit breaker is open.  Logs warnings for other error conditions.
        """
        body: dict[str, Any] = {
            "claim_id": claim_id,
            "claimant_id": claimant_id,
        }
        if date_range is not None:
            body["date_range"] = {"start": date_range[0], "end": date_range[1]}
        try:
            resp = self._client.post(self._query_path, json=body)
            parsed = safe_adapter_json_dict(resp, log_label="medical_records_rest")
            if parsed is None:
                return None
            data = extract_response_envelope(parsed, self._response_key)
            if not isinstance(data, dict):
                logger.warning(
                    "Medical records REST API returned unexpected type: %s",
                    type(data).__name__,
                )
                return None
            return data
        except CircuitOpenError:
            logger.warning("Medical records adapter circuit breaker open; returning None")
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            logger.warning("Medical records adapter HTTP error: %s", exc, exc_info=True)
            return None
        except httpx.RequestError as exc:
            logger.warning("Medical records adapter request error: %s", exc, exc_info=True)
            return None

    def health_check(self) -> tuple[bool, str]:
        """Probe the HIE/provider portal API for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_medical_records_adapter() -> RestMedicalRecordsAdapter:
    """Build a REST medical records adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().medical_records_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "MEDICAL_RECORDS_REST_BASE_URL is required when MEDICAL_RECORDS_ADAPTER=rest. "
            "Set MEDICAL_RECORDS_REST_BASE_URL to your HIE or provider portal base URL."
        )
    return RestMedicalRecordsAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value.get_secret_value(),
        query_path=cfg.query_path,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
    )
