"""REST SIU (Special Investigations Unit) adapter for connecting to an external case management API.

Configure via environment variables:

- SIU_REST_BASE_URL: Base URL (e.g. https://siu.example.com/api/v1)
- SIU_REST_AUTH_HEADER: Auth header name (default: Authorization)
- SIU_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- SIU_REST_CASES_PATH: Path for creating/getting cases (default: /siu/cases)
- SIU_REST_NOTES_PATH_TEMPLATE: Path template for adding notes; {case_id} placeholder
  (default: /siu/cases/{case_id}/notes)
- SIU_REST_STATUS_PATH_TEMPLATE: Path template for updating status; {case_id} placeholder
  (default: /siu/cases/{case_id}/status)
- SIU_REST_RESPONSE_KEY: Optional JSON key wrapping the payload (e.g. data)
- SIU_REST_TIMEOUT: Request timeout in seconds (default: 15)
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from claim_agent.adapters.base import SIUAdapter
from claim_agent.adapters.http_client import (
    AdapterHttpClient,
    CircuitOpenError,
    extract_response_envelope,
)

logger = logging.getLogger(__name__)


class RestSIUAdapter(SIUAdapter):
    """SIU adapter backed by a real REST case-management API.

    Expected API contract:

    * ``POST {cases_path}`` with JSON ``{claim_id, indicators}`` → 200/201 JSON with
      ``case_id`` (or ``id`` / ``caseId``).
    * ``GET {cases_path}/{case_id}`` → 200 JSON for case details, 404 when not found.
    * ``POST {notes_path_template}`` with JSON ``{note, category}`` → 200/201 on success.
    * ``POST {status_path_template}`` with JSON ``{status}`` → 200 on success (some gateways
      use PUT/PATCH instead; configure paths accordingly).
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        cases_path: str = "/siu/cases",
        notes_path_template: str = "/siu/cases/{case_id}/notes",
        status_path_template: str = "/siu/cases/{case_id}/status",
        response_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._client = AdapterHttpClient(
            base_url=base_url,
            auth_header=auth_header,
            auth_value=auth_value,
            timeout=timeout,
        )
        self._cases_path = cases_path
        self._notes_path_template = notes_path_template.strip()
        self._status_path_template = status_path_template.strip()
        self._response_key = (response_key or "").strip() or None

    def _extract_case_id(self, raw: Any) -> str:
        """Pull case_id from the API create-case response."""
        data = extract_response_envelope(raw, self._response_key)
        if isinstance(data, dict):
            for key in ("case_id", "id", "caseId", "siu_case_id"):
                val = data.get(key)
                if val is not None:
                    return str(val)
        raise ValueError(
            f"SIU REST API response does not contain a recognisable case ID: {raw!r}"
        )

    def create_case(self, claim_id: str, indicators: list[str]) -> str:
        body: dict[str, Any] = {"claim_id": claim_id, "indicators": indicators}
        resp = self._client.post(self._cases_path, json=body)
        return self._extract_case_id(resp.json())

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        encoded = quote(case_id, safe="")
        path = f"{self._cases_path}/{encoded}"
        try:
            resp = self._client.get(path)
        except CircuitOpenError:
            logger.warning("SIU adapter circuit breaker open; returning None")
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        raw = extract_response_envelope(resp.json(), self._response_key)
        return raw if isinstance(raw, dict) else None

    def add_investigation_note(self, case_id: str, note: str, category: str = "general") -> bool:
        encoded = quote(case_id, safe="")
        path = self._notes_path_template.replace("{case_id}", encoded)
        body: dict[str, Any] = {"note": note, "category": category}
        try:
            resp = self._client.post(path, json=body)
            return resp.is_success
        except (CircuitOpenError, httpx.HTTPStatusError):
            logger.warning("SIU adapter failed to add investigation note", exc_info=True)
            return False

    def update_case_status(self, case_id: str, status: str) -> bool:
        encoded = quote(case_id, safe="")
        path = self._status_path_template.replace("{case_id}", encoded)
        body: dict[str, Any] = {"status": status}
        try:
            resp = self._client.post(path, json=body)
            return resp.is_success
        except (CircuitOpenError, httpx.HTTPStatusError):
            logger.warning("SIU adapter failed to update case status", exc_info=True)
            return False

    def health_check(self) -> tuple[bool, str]:
        """Probe the SIU API for liveness."""
        return self._client.health_check_with_fallback()


def create_rest_siu_adapter() -> RestSIUAdapter:
    """Build a REST SIU adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().siu_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "SIU_REST_BASE_URL is required when SIU_ADAPTER=rest. "
            "Set SIU_REST_BASE_URL to your SIU case management API base URL."
        )
    return RestSIUAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value,
        cases_path=cfg.cases_path,
        notes_path_template=cfg.notes_path_template,
        status_path_template=cfg.status_path_template,
        response_key=cfg.response_key or None,
        timeout=cfg.timeout,
    )
