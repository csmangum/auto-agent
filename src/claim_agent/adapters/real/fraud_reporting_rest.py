"""REST fraud-reporting adapter for state bureau, NICB, and NISS submissions."""

from __future__ import annotations

from typing import Any

from claim_agent.adapters.base import FraudReportingAdapter
from claim_agent.adapters.http_client import AdapterHttpClient
from claim_agent.config import get_settings


def _to_string(value: Any, fallback: str = "") -> str:
    if value is None:
        return fallback
    s = str(value).strip()
    return s if s else fallback


def _coerce_indicators_count(raw: Any, fallback: int) -> int:
    if raw is None:
        return fallback
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return fallback
    return n if n >= 0 else fallback


class RestFraudReportingAdapter(FraudReportingAdapter):
    """HTTP-backed fraud filing adapter with configurable endpoint paths."""

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        timeout: float = 15.0,
        state_bureau_path: str = "/fraud/state-bureau",
        nicb_path: str = "/fraud/nicb",
        niss_path: str = "/fraud/niss",
        response_key: str | None = None,
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
            adapter_name="fraud_reporting",
        )
        self._state_bureau_path = state_bureau_path
        self._nicb_path = nicb_path
        self._niss_path = niss_path
        self._response_key = (response_key or "").strip() or None

    def _extract_payload(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            return {}
        if not self._response_key:
            return raw
        nested = raw.get(self._response_key)
        return nested if isinstance(nested, dict) else {}

    def file_state_bureau_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            **(payload or {}),
            "claim_id": claim_id,
            "case_id": case_id,
            "state": state,
            "indicators": indicators,
        }
        resp = self._client.post(self._state_bureau_path, json=body)
        parsed = self._extract_payload(resp.json())
        return {
            "report_id": _to_string(parsed.get("report_id")),
            "state": _to_string(parsed.get("state"), state or "California"),
            "indicators_count": _coerce_indicators_count(
                parsed.get("indicators_count"), len(indicators)
            ),
            "message": _to_string(parsed.get("message"), "State bureau report filed"),
        }

    def file_nicb_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        report_type: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        resp = self._client.post(
            self._nicb_path,
            json={
                "claim_id": claim_id,
                "case_id": case_id,
                "report_type": report_type,
                "indicators": indicators,
            },
        )
        payload = self._extract_payload(resp.json())
        return {
            "report_id": _to_string(payload.get("report_id")),
            "report_type": _to_string(payload.get("report_type"), report_type),
            "indicators_count": _coerce_indicators_count(
                payload.get("indicators_count"), len(indicators)
            ),
            "message": _to_string(payload.get("message"), "NICB report filed"),
        }

    def file_niss_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        report_type: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        resp = self._client.post(
            self._niss_path,
            json={
                "claim_id": claim_id,
                "case_id": case_id,
                "report_type": report_type,
                "indicators": indicators,
            },
        )
        payload = self._extract_payload(resp.json())
        return {
            "report_id": _to_string(payload.get("report_id")),
            "report_type": _to_string(payload.get("report_type"), report_type),
            "indicators_count": _coerce_indicators_count(
                payload.get("indicators_count"), len(indicators)
            ),
            "message": _to_string(payload.get("message"), "NISS report filed"),
        }


def create_rest_fraud_reporting_adapter() -> RestFraudReportingAdapter:
    """Build REST fraud-reporting adapter from settings."""
    cfg = get_settings().fraud_reporting_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "FRAUD_REPORTING_REST_BASE_URL is required when FRAUD_REPORTING_ADAPTER=rest."
        )
    return RestFraudReportingAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value.get_secret_value(),
        timeout=cfg.timeout,
        state_bureau_path=cfg.state_bureau_path,
        nicb_path=cfg.nicb_path,
        niss_path=cfg.niss_path,
        response_key=cfg.response_key or None,
        circuit_failure_threshold=cfg.circuit_failure_threshold,
        circuit_recovery_timeout=cfg.circuit_recovery_timeout,
    )
