"""REST adapter for state bureau fraud report filing."""

from __future__ import annotations

from typing import Any

import httpx

from claim_agent.adapters.base import StateBureauAdapter
from claim_agent.adapters.http_client import AdapterHttpClient, CircuitOpenError
from claim_agent.adapters.state_bureau_common import normalize_state_name_and_code

_TRANSIENT_HTTP_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})


class RestStateBureauAdapter(StateBureauAdapter):
    """POST fraud report payloads to per-state bureau endpoints."""

    def __init__(
        self,
        *,
        auth_header: str = "Authorization",
        auth_value: str = "",
        timeout: float = 15.0,
        state_endpoints: dict[str, str] | None = None,
        circuit_failure_threshold: int = 5,
        circuit_recovery_timeout: float = 60.0,
    ) -> None:
        self._auth_header = auth_header
        self._auth_value = auth_value
        self._timeout = timeout
        self._circuit_failure_threshold = circuit_failure_threshold
        self._circuit_recovery_timeout = circuit_recovery_timeout
        self._state_endpoints = {
            k.strip().upper(): (v or "").strip()
            for k, v in (state_endpoints or {}).items()
            if k and (v or "").strip()
        }
        self._clients: dict[str, AdapterHttpClient] = {}

    def _get_client_for_state(self, state_code: str) -> AdapterHttpClient:
        base_url = self._state_endpoints.get(state_code)
        if not base_url:
            raise ValueError(
                f"No state bureau endpoint configured for {state_code}. "
                f"Set STATE_BUREAU_{state_code}_ENDPOINT."
            )
        client = self._clients.get(state_code)
        if client is None:
            client = AdapterHttpClient(
                base_url=base_url,
                auth_header=self._auth_header,
                auth_value=self._auth_value,
                timeout=self._timeout,
                circuit_failure_threshold=self._circuit_failure_threshold,
                circuit_recovery_timeout=self._circuit_recovery_timeout,
                adapter_name=f"state_bureau_{state_code}",
            )
            self._clients[state_code] = client
        return client

    def health_check(self) -> tuple[bool, str]:
        """Probe each configured state bureau base URL for liveness."""
        if not self._state_endpoints:
            return False, "no state bureau endpoints configured"
        parts: list[str] = []
        all_ok = True
        for code in sorted(self._state_endpoints.keys()):
            client = self._get_client_for_state(code)
            ok, msg = client.health_check_with_fallback()
            if not ok:
                all_ok = False
                parts.append(f"{code}:{msg}")
        if all_ok:
            return True, "ok"
        return False, "; ".join(parts)

    def submit_fraud_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        state_norm, state_code = normalize_state_name_and_code(state)
        payload = {
            "claim_id": claim_id,
            "case_id": case_id,
            "state": state_norm,
            "state_code": state_code,
            "indicators": indicators,
        }
        client = self._get_client_for_state(state_code)
        try:
            response = client.post("/fraud-reports", json=payload)
        except CircuitOpenError as e:
            raise ConnectionError(str(e)) from e
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code in _TRANSIENT_HTTP_STATUS_CODES:
                raise ConnectionError(f"state bureau transient HTTP failure: {e}") from e
            raise
        except httpx.HTTPError as e:
            raise ConnectionError(f"state bureau transport failure: {e}") from e

        try:
            data = response.json()
        except ValueError as e:
            raise ValueError("State bureau response was not valid JSON") from e
        if not isinstance(data, dict):
            raise ValueError("State bureau response must be a JSON object")
        report_id_raw = data.get("report_id") or data.get("id")
        if not isinstance(report_id_raw, str) or not report_id_raw.strip():
            raise ValueError("State bureau response missing report_id")
        report_id = report_id_raw.strip()
        message_raw = data.get("message")
        message = (
            message_raw
            if isinstance(message_raw, str) and message_raw.strip()
            else f"Fraud report filed with {state_norm} fraud bureau. Report ID: {report_id}"
        )
        metadata_raw = data.get("metadata")
        metadata = metadata_raw if isinstance(metadata_raw, dict) else {}
        return {
            "report_id": report_id,
            "state": state_norm,
            "message": message,
            "metadata": metadata,
        }
