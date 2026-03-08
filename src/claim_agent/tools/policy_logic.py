"""Policy database lookup logic."""

import json
import logging

from claim_agent.adapters.base import PolicyAdapter
from claim_agent.adapters.registry import get_policy_adapter

logger = logging.getLogger(__name__)


def query_policy_db_impl(
    policy_number: str,
    *,
    policy_adapter: PolicyAdapter | None = None,
) -> str:
    if not policy_number or not isinstance(policy_number, str):
        return json.dumps({"valid": False, "message": "Invalid policy number"})
    policy_number = policy_number.strip()
    if not policy_number:
        return json.dumps({"valid": False, "message": "Empty policy number"})
    adapter = policy_adapter or get_policy_adapter()
    try:
        p = adapter.get_policy(policy_number)
    except NotImplementedError as exc:
        logger.warning("Policy adapter get_policy not implemented: %s", exc)
        return json.dumps({
            "valid": False,
            "message": "Policy lookup is not supported by the configured adapter",
            "error": "not_implemented",
        })
    except Exception:
        logger.exception("Unexpected error while querying policy adapter")
        return json.dumps({
            "valid": False,
            "message": "Error querying policy database",
            "error": "adapter_error",
        })
    if p is not None:
        status = p.get("status", "active")
        is_active = isinstance(status, str) and status.lower() == "active"
        if is_active:
            return json.dumps({
                "valid": True,
                "coverage": p.get("coverage", "comprehensive"),
                "deductible": p.get("deductible", 500),
                "status": status,
            })
        return json.dumps({
            "valid": False,
            "status": status,
            "message": "Policy not found or inactive",
        })
    return json.dumps({"valid": False, "message": "Policy not found or inactive"})
