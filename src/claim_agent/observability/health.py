"""Production health checks for database, optional dependencies, and adapters."""

import logging
import os

from sqlalchemy import text

from claim_agent.config.llm import get_llm
from claim_agent.config.settings import get_adapter_backend
from claim_agent.config.settings_model import (
    REST_CAPABLE_ADAPTERS,
    VALID_ADAPTER_BACKENDS,
    VALUATION_PROVIDER_BACKENDS,
)
from claim_agent.db.database import get_connection, get_replica_connection, has_read_replica

logger = logging.getLogger(__name__)


def _evaluate_adapter_health(adapter: object) -> str:
    """Run ``adapter.health_check()`` if present; return check status string."""
    hc = getattr(adapter, "health_check", None)
    if not callable(hc):
        return "skipped"
    try:
        raw = hc()
    except Exception as e:
        logger.exception("Adapter health_check() raised: %s", e)
        return f"error:{e!s}"
    if not isinstance(raw, tuple) or len(raw) != 2:
        return f"error:health_check must return (bool, str), got {type(raw).__name__!r}"
    ok, msg = raw[0], raw[1]
    if not isinstance(ok, bool):
        return f"error:health_check bool expected, got {type(ok).__name__!r}"
    return "ok" if ok else f"degraded:{msg}"


def _check_adapters() -> dict[str, str]:
    """Run health checks on adapters that support health_check()."""
    checks: dict[str, str] = {}
    adapters_to_check = [
        ("policy", "get_policy_adapter"),
        ("valuation", "get_valuation_adapter"),
        ("repair_shop", "get_repair_shop_adapter"),
        ("parts", "get_parts_adapter"),
        ("siu", "get_siu_adapter"),
        ("fraud_reporting", "get_fraud_reporting_adapter"),
        ("state_bureau", "get_state_bureau_adapter"),
        ("claim_search", "get_claim_search_adapter"),
        ("erp", "get_erp_adapter"),
        ("nmvtis", "get_nmvtis_adapter"),
        ("gap_insurance", "get_gap_insurance_adapter"),
        ("ocr", "get_ocr_adapter"),
        ("cms", "get_cms_reporting_adapter"),
        ("reverse_image", "get_reverse_image_adapter"),
    ]
    for name, getter_name in adapters_to_check:
        backend = get_adapter_backend(name)
        if name == "valuation":
            backend_ok = backend in VALID_ADAPTER_BACKENDS or backend in VALUATION_PROVIDER_BACKENDS
        else:
            backend_ok = backend in VALID_ADAPTER_BACKENDS
        if not backend_ok:
            checks[f"adapter_{name}"] = f"degraded:invalid backend {backend!r}"
            continue
        if backend == "rest" and name not in REST_CAPABLE_ADAPTERS:
            checks[f"adapter_{name}"] = f"degraded:rest backend not supported for {name} adapter"
            continue
        if name == "valuation" and backend in VALUATION_PROVIDER_BACKENDS:
            try:
                from claim_agent.adapters import registry

                getter = getattr(registry, getter_name)
                adapter = getter()
                checks[f"adapter_{name}"] = _evaluate_adapter_health(adapter)
            except Exception as e:
                logger.exception("Adapter %s health check failed: %s", name, e)
                checks[f"adapter_{name}"] = f"error:{e!s}"
            continue
        if backend != "rest":
            checks[f"adapter_{name}"] = "skipped"
            continue
        try:
            from claim_agent.adapters import registry

            getter = getattr(registry, getter_name)
            adapter = getter()
            checks[f"adapter_{name}"] = _evaluate_adapter_health(adapter)
        except Exception as e:
            logger.exception("Adapter %s health check failed: %s", name, e)
            checks[f"adapter_{name}"] = f"error:{e!s}"
    return checks


def check_health() -> dict:
    """Run health checks and return status dict.

    Returns:
        Dict with keys:
        - status: "ok" | "degraded"
        - checks: database, database_replica, llm, and per-adapter keys
          ``adapter_<name>`` for policy, valuation, repair_shop, parts, siu,
          fraud_reporting, state_bureau, claim_search, erp, nmvtis, gap_insurance,
          ocr, cms, reverse_image. Each adapter value is "ok", "degraded:msg",
          "skipped", or "error:...".
    """
    checks: dict[str, str] = {}
    db_ok = _check_database()
    checks["database"] = "ok" if db_ok else "error"

    if has_read_replica():
        replica_ok = _check_replica_database()
        checks["database_replica"] = "ok" if replica_ok else "error"
    else:
        checks["database_replica"] = "skipped"

    if os.environ.get("HEALTH_CHECK_LLM", "").strip().lower() in ("true", "1", "yes"):
        checks["llm"] = "ok" if _check_llm() else "degraded"
    else:
        checks["llm"] = "skipped"

    adapter_checks = _check_adapters()
    checks.update(adapter_checks)

    overall = "ok" if db_ok else "degraded"
    return {"status": overall, "checks": checks}


def is_healthy() -> bool:
    """Return True if all critical dependencies are healthy (DB connected)."""
    result = check_health()
    return bool(result.get("status") == "ok")


def _check_database() -> bool:
    """Verify database connectivity. Returns True if ok."""
    try:
        with get_connection() as conn:
            conn.execute(text("SELECT 1")).fetchone()
        return True
    except Exception:
        return False


def _check_replica_database() -> bool:
    """Verify read-replica connectivity. Returns True if ok."""
    try:
        with get_replica_connection() as conn:
            conn.execute(text("SELECT 1")).fetchone()
        return True
    except Exception:
        return False


def _check_llm() -> bool:
    """Verify LLM is configurable (get_llm returns a client). Does not call the LLM."""
    try:
        llm = get_llm()
        return llm is not None
    except Exception:
        return False
