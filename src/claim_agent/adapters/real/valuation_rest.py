"""HTTP valuation adapters for CCC-, Mitchell-, and Audatex-style PAS endpoints.

Production APIs differ by carrier; this module sends a configurable GET request and
normalizes JSON into ``{value, condition, source, comparables}``.

Set ``VALUATION_ADAPTER`` to ``ccc``, ``mitchell``, or ``audatex`` and configure
``VALUATION_REST_*`` (see :class:`ValuationRestConfig`).
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

import httpx

from claim_agent.adapters.base import ValuationAdapter
from claim_agent.adapters.http_client import AdapterHttpClient, CircuitOpenError

logger = logging.getLogger(__name__)

# Suggested path templates (override with VALUATION_REST_PATH_TEMPLATE).
# Placeholders are URL-encoded by the adapter before format().
DEFAULT_VALUATION_PATH_TEMPLATES: dict[str, str] = {
    "ccc": "/vehicle-valuation?vin={vin}&year={year}&make={make}&model={model}",
    "mitchell": "/vehicle-valuation?vin={vin}&year={year}&make={make}&model={model}",
    "audatex": "/vehicle-valuation?vin={vin}&year={year}&make={make}&model={model}",
}


def normalize_valuation_response(
    raw: Any,
    *,
    default_source: str,
) -> dict[str, Any] | None:
    """Map vendor JSON to the valuation contract, or None if no ACV/value."""
    if not isinstance(raw, dict):
        return None

    val: float | None = None
    for k in (
        "value",
        "acv",
        "vehicle_value",
        "appraised_value",
        "adjusted_vehicle_value",
    ):
        if k not in raw or raw[k] is None:
            continue
        try:
            val = float(raw[k])
            break
        except (TypeError, ValueError):
            continue
    if val is None:
        return None

    cond = raw.get("condition") or raw.get("vehicle_condition") or "good"
    cond_s = cond if isinstance(cond, str) else str(cond)

    src = raw.get("source") or raw.get("provider") or default_source
    src_s = src if isinstance(src, str) else str(src)

    comps_raw = None
    for k in ("comparables", "comparable_vehicles", "comps"):
        if k in raw and raw[k] is not None:
            comps_raw = raw[k]
            break
    if comps_raw is None:
        comps_raw = []
    comparables: list[dict[str, Any]] = []
    if isinstance(comps_raw, list):
        for item in comps_raw:
            if not isinstance(item, dict):
                continue
            price = None
            for pk in ("price", "amount", "value"):
                if pk in item and item[pk] is not None:
                    price = item[pk]
                    break
            try:
                pf = float(price) if price is not None else None
            except (TypeError, ValueError):
                pf = None
            if pf is None:
                continue
            cy = item.get("year")
            try:
                yi = int(cy) if cy is not None else 0
            except (TypeError, ValueError):
                yi = 0
            mil = item.get("mileage")
            try:
                mi = int(mil) if mil is not None else 0
            except (TypeError, ValueError):
                mi = 0
            comparables.append(
                {
                    "vin": str(item.get("vin") or ""),
                    "year": yi,
                    "make": str(item.get("make") or ""),
                    "model": str(item.get("model") or ""),
                    "price": pf,
                    "mileage": mi,
                    "source": str(item.get("source") or default_source),
                }
            )

    return {
        "value": val,
        "condition": cond_s,
        "source": src_s,
        "comparables": comparables,
    }


class RestValuationAdapter(ValuationAdapter):
    """GET JSON valuation from a REST gateway; normalize to tool contract."""

    def __init__(
        self,
        *,
        provider: str,
        base_url: str,
        auth_header: str = "Authorization",
        auth_value: str = "",
        path_template: str,
        response_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._provider = provider
        self._response_key = (response_key or "").strip() or None
        self._client = AdapterHttpClient(
            base_url=base_url,
            auth_header=auth_header,
            auth_value=auth_value,
            timeout=timeout,
        )
        _required = ("{vin}", "{year}")
        for _placeholder in _required:
            if _placeholder not in path_template:
                raise ValueError(
                    f"VALUATION_REST_PATH_TEMPLATE is missing required placeholder"
                    f" '{_placeholder}': {path_template!r}"
                )
        self._path_template = path_template

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        vin_q = quote((vin or "").strip(), safe="")
        make_q = quote((make or "").strip(), safe="")
        model_q = quote((model or "").strip(), safe="")
        try:
            y = int(year)
        except (TypeError, ValueError):
            y = 0
        path = self._path_template.format(
            vin=vin_q,
            year=y,
            make=make_q,
            model=model_q,
        )
        try:
            resp = self._client.get(path)
        except CircuitOpenError:
            logger.warning("Valuation adapter circuit open (provider=%s)", self._provider)
            return None
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 404:
                return None
            logger.exception("Valuation HTTP error provider=%s", self._provider)
            raise
        except httpx.HTTPError:
            logger.exception("Valuation request failed provider=%s", self._provider)
            raise

        try:
            data = resp.json()
        except ValueError:
            logger.warning("Valuation response not JSON provider=%s", self._provider)
            return None

        if not isinstance(data, dict):
            return None
        if self._response_key:
            inner = data.get(self._response_key)
            if not isinstance(inner, dict):
                logger.warning(
                    "Valuation response missing key %r provider=%s",
                    self._response_key,
                    self._provider,
                )
                return None
            data = inner

        return normalize_valuation_response(
            data,
            default_source=self._provider,
        )

    def health_check(self, path: str = "/health") -> tuple[bool, str]:
        """Probe gateway liveness (same pattern as policy REST adapter)."""
        ok, msg = self._client.health_check(path=path)
        if not ok and "status=404" in msg:
            ok, msg = self._client.health_check(path="/")
        return ok, msg


def create_valuation_rest_adapter(provider: str) -> RestValuationAdapter:
    """Build adapter from ``get_settings().valuation_rest`` and provider name."""
    from claim_agent.config import get_settings

    p = provider.strip().lower()
    cfg = get_settings().valuation_rest
    base = (cfg.base_url or "").strip()
    if not base:
        raise ValueError(
            f"VALUATION_REST_BASE_URL is required when VALUATION_ADAPTER={p}. "
            "Set it to your valuation gateway base URL."
        )
    tmpl = (cfg.path_template or "").strip() or DEFAULT_VALUATION_PATH_TEMPLATES.get(
        p, DEFAULT_VALUATION_PATH_TEMPLATES["ccc"]
    )
    rk = (cfg.response_key or "").strip() or None
    return RestValuationAdapter(
        provider=p,
        base_url=base,
        auth_header=cfg.auth_header,
        auth_value=cfg.auth_value,
        path_template=tmpl,
        response_key=rk,
        timeout=cfg.timeout,
    )
