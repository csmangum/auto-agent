"""REST ERP adapter — HTTP-backed integration with repair/shop management systems.

Sends signed JSON requests to a vendor ERP API for outbound events (assignment,
estimate updates, status changes) and polls for inbound events (estimate approvals,
parts delays, supplement requests).

Configure via ``ERP_REST_*`` environment variables when ``ERP_ADAPTER=rest``.
"""

from __future__ import annotations

import logging
from typing import Any

from claim_agent.adapters.base import ERPAdapter
from claim_agent.adapters.http_client import AdapterHttpClient

logger = logging.getLogger(__name__)


class RestERPAdapter(ERPAdapter):
    """HTTP-backed ERP adapter.

    All outbound calls are POSTs to ``<base_url>/<path>`` with a JSON body.
    Inbound polling is a GET to the configured ``events_path``.

    Parameters
    ----------
    base_url:
        ERP API base URL (e.g. ``https://erp.example.com/api/v2``).
    auth_header:
        Name of the HTTP authentication header (e.g. ``Authorization``).
    auth_value:
        Value for the auth header (e.g. ``Bearer <token>``).
    timeout:
        Per-request timeout in seconds.
    shop_id_map:
        Optional dict mapping internal shop IDs to ERP tenant/location IDs.
    assignment_path:
        API path for repair assignment notifications.
    estimate_path:
        API path for estimate/supplement updates.
    status_path:
        API path for repair status changes.
    events_path:
        API path for polling inbound events.
    """

    def __init__(
        self,
        *,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        timeout: float = 15.0,
        shop_id_map: dict[str, str] | None = None,
        assignment_path: str = "/repairs/assignment",
        estimate_path: str = "/repairs/estimate",
        status_path: str = "/repairs/status",
        events_path: str = "/repairs/events",
    ) -> None:
        self._client = AdapterHttpClient(
            base_url=base_url,
            auth_header=auth_header,
            auth_value=auth_value,
            timeout=timeout,
        )
        self._shop_id_map: dict[str, str] = dict(shop_id_map or {})
        self._assignment_path = assignment_path
        self._estimate_path = estimate_path
        self._status_path = status_path
        self._events_path = events_path

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def resolve_shop_id(self, internal_shop_id: str) -> str:
        return self._shop_id_map.get(internal_shop_id, internal_shop_id)

    # ------------------------------------------------------------------
    # Outbound – carrier → ERP
    # ------------------------------------------------------------------

    def push_repair_assignment(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        repair_amount: float | None,
        vehicle_info: dict[str, Any] | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "claim_id": claim_id,
            "shop_id": self.resolve_shop_id(shop_id),
            "authorization_id": authorization_id,
            "repair_amount": repair_amount,
            "vehicle_info": vehicle_info or {},
        }
        resp = self._client.post(self._assignment_path, json=body)
        return _extract_result(resp.json())

    def push_estimate_update(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        estimate_amount: float,
        line_items: list[dict[str, Any]] | None,
        is_supplement: bool,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "claim_id": claim_id,
            "shop_id": self.resolve_shop_id(shop_id),
            "authorization_id": authorization_id,
            "estimate_amount": round(float(estimate_amount), 2),
            "line_items": line_items or [],
            "is_supplement": is_supplement,
        }
        resp = self._client.post(self._estimate_path, json=body)
        return _extract_result(resp.json())

    def push_repair_status(
        self,
        *,
        claim_id: str,
        shop_id: str,
        authorization_id: str | None,
        status: str,
        notes: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "claim_id": claim_id,
            "shop_id": self.resolve_shop_id(shop_id),
            "authorization_id": authorization_id,
            "status": status,
            "notes": notes,
        }
        resp = self._client.post(self._status_path, json=body)
        return _extract_result(resp.json())

    # ------------------------------------------------------------------
    # Inbound – ERP → carrier (polling)
    # ------------------------------------------------------------------

    def pull_pending_events(
        self,
        *,
        shop_id: str | None = None,
        since: str | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if shop_id:
            params["shop_id"] = self.resolve_shop_id(shop_id)
        if since:
            params["since"] = since
        resp = self._client.get(self._events_path, params=params)
        raw = resp.json()
        items = raw if isinstance(raw, list) else raw.get("events") or []
        return [item for item in items if isinstance(item, dict)]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def _extract_result(raw: Any) -> dict[str, Any]:
    """Normalize an ERP API response to a canonical result dict."""
    if not isinstance(raw, dict):
        return {"erp_reference": "", "status": "unknown"}
    ref = str(
        raw.get("erp_reference")
        or raw.get("reference")
        or raw.get("id")
        or ""
    )
    status = str(raw.get("status") or "submitted")
    result: dict[str, Any] = {"erp_reference": ref, "status": status}
    for key in ("approved_amount", "message", "denial_reason"):
        if key in raw:
            result[key] = raw[key]
    return result


def create_rest_erp_adapter() -> RestERPAdapter:
    """Build a REST ERP adapter from environment settings."""
    from claim_agent.config import get_settings

    cfg = get_settings().erp_rest
    if not cfg.base_url.strip():
        raise ValueError(
            "ERP_REST_BASE_URL is required when ERP_ADAPTER=rest. "
            "Set ERP_REST_BASE_URL to your ERP API base URL."
        )
    return RestERPAdapter(
        base_url=cfg.base_url,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value,
        timeout=cfg.timeout,
        shop_id_map=cfg.shop_id_map,
        assignment_path=cfg.assignment_path,
        estimate_path=cfg.estimate_path,
        status_path=cfg.status_path,
        events_path=cfg.events_path,
    )
