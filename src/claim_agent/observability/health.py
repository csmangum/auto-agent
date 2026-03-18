"""Production health checks for database and optional dependencies."""

import os

from sqlalchemy import text

from claim_agent.config.llm import get_llm
from claim_agent.db.database import get_connection


def check_health() -> dict:
    """Run health checks and return status dict.

    Returns:
        Dict with keys:
        - status: "ok" | "degraded"
        - checks: {"database": "ok"|"error", "llm": "ok"|"degraded"|"skipped"}
    """
    checks: dict[str, str] = {}
    db_ok = _check_database()
    checks["database"] = "ok" if db_ok else "error"

    if os.environ.get("HEALTH_CHECK_LLM", "").strip().lower() in ("true", "1", "yes"):
        checks["llm"] = "ok" if _check_llm() else "degraded"
    else:
        checks["llm"] = "skipped"

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
