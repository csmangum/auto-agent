"""Production health checks for database, optional dependencies, and adapters."""

import logging
import os

from sqlalchemy import text

from claim_agent.config.llm import get_llm
from claim_agent.config.settings import get_adapter_backend
from claim_agent.db.database import get_connection

logger = logging.getLogger(__name__)


def _check_adapters() -> dict[str, str]:
    """Run health checks on adapters that support health_check()."""
    checks: dict[str, str] = {}
    adapters_to_check = [
        ("policy", "get_policy_adapter"),
        ("valuation", "get_valuation_adapter"),
        ("repair_shop", "get_repair_shop_adapter"),
        ("parts", "get_parts_adapter"),
        ("siu", "get_siu_adapter"),
    ]
    for name, getter_name in adapters_to_check:
        backend = get_adapter_backend(name)
        if backend != "rest":
            checks[f"adapter_{name}"] = "skipped"
            continue
        try:
            from claim_agent.adapters import registry

            getter = getattr(registry, getter_name)
            adapter = getter()
            if hasattr(adapter, "health_check"):
                ok, msg = adapter.health_check()
                checks[f"adapter_{name}"] = "ok" if ok else f"degraded:{msg}"
            else:
                checks[f"adapter_{name}"] = "skipped"
        except Exception as e:
            logger.error("Adapter %s health check failed: %s", name, e)
            checks[f"adapter_{name}"] = f"error:{e!s}"
    return checks


def check_health() -> dict:
    """Run health checks and return status dict.

    Returns:
        Dict with keys:
        - status: "ok" | "degraded"
        - checks: {"database": "ok"|"error", "llm": "ok"|"degraded"|"skipped",
                   "adapter_*": "ok"|"degraded:msg"|"skipped"}
    """
    checks: dict[str, str] = {}
    db_ok = _check_database()
    checks["database"] = "ok" if db_ok else "error"

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


def _check_llm() -> bool:
    """Verify LLM is configurable (get_llm returns a client). Does not call the LLM."""
    try:
        llm = get_llm()
        return llm is not None
    except Exception:
        return False
