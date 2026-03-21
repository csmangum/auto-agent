"""REST-based policy adapter for Policy Administration System (PAS) integration.

Calls a generic REST API to fetch policy data. Configure via environment:

- POLICY_REST_BASE_URL: Base URL (e.g. https://pas.example.com/api/v1)
- POLICY_REST_AUTH_HEADER: Auth header name (default: Authorization)
- POLICY_REST_AUTH_VALUE: Auth value (e.g. Bearer sk-... or empty)
- POLICY_REST_PATH_TEMPLATE: Path template, {policy_number} placeholder (default: /policies/{policy_number})
- POLICY_REST_RESPONSE_KEY: Optional JSON key for policy (e.g. "data" if API returns {"data": {...}})
"""

import logging
from typing import Any
from urllib.parse import quote

import httpx

from claim_agent.adapters.base import PolicyAdapter
from claim_agent.adapters.http_client import AdapterHttpClient, CircuitOpenError

logger = logging.getLogger(__name__)


def _default_path_template() -> str:
    return "/policies/{policy_number}"


class RestPolicyAdapter(PolicyAdapter):
    """Policy adapter that fetches from a REST PAS API.

    Expected API contract:
    - GET {base_url}/policies/{policy_number} returns 200 with JSON policy, or 404 when not found.
    - Policy JSON should include: status, and either coverages/collision_deductible/etc. (new format)
      or coverage/deductible (legacy format).
    - Optional FNOL fields: effective_date, expiration_date (ISO YYYY-MM-DD), or term_start/term_end
      aliases, for incident-vs-policy-term coverage verification.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        path_template: str | None = None,
        response_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._client = AdapterHttpClient(
            base_url=base_url,
            auth_header=auth_header,
            auth_value=auth_value,
            timeout=timeout,
        )
        self._path_template = (path_template or _default_path_template()).strip()
        self._response_key = (response_key or "").strip() or None

    def get_policy(self, policy_number: str) -> dict[str, Any] | None:
        encoded = quote(policy_number, safe="")
        path = self._path_template.replace("{policy_number}", encoded)
        try:
            resp = self._client.get(path)
        except CircuitOpenError:
            logger.warning("Policy adapter circuit breaker open; returning None")
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            raise
        if not resp.is_success:
            resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None
        if self._response_key:
            if self._response_key not in data:
                logger.warning("Response key %r not found in policy API response", self._response_key)
                return None
            inner = data[self._response_key]
            if not isinstance(inner, dict):
                return None
            return inner
        return data

    def health_check(self) -> tuple[bool, str]:
        """Probe the PAS API for liveness."""
        ok, msg = self._client.health_check(path="/health")
        if not ok and "status=404" in msg:
            ok, msg = self._client.health_check(path="/")
        return ok, msg
