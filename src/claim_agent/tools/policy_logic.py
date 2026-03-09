"""Policy database lookup logic."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from claim_agent.adapters.registry import get_policy_adapter
from claim_agent.exceptions import AdapterError, DomainValidationError

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)


def query_policy_db_impl(
    policy_number: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    if not policy_number or not isinstance(policy_number, str):
        raise DomainValidationError("Invalid policy number")
    policy_number = policy_number.strip()
    if not policy_number:
        raise DomainValidationError("Empty policy number")
    adapter = ctx.adapters.policy if ctx else get_policy_adapter()
    try:
        p = adapter.get_policy(policy_number)
    except NotImplementedError as exc:
        logger.warning("Policy adapter get_policy not implemented: %s", exc)
        raise AdapterError("Policy lookup is not supported by the configured adapter") from exc
    except Exception as exc:
        logger.exception("Unexpected error while querying policy adapter")
        raise AdapterError("Error querying policy database") from exc
    if p is not None:
        status = p.get("status", "active")
        is_active = isinstance(status, str) and status.lower() == "active"
        if is_active:
            result = {
                "valid": True,
                "coverage": p.get("coverage", "comprehensive"),
                "deductible": p.get("deductible", 500),
                "status": status,
            }
            rental = p.get("rental_reimbursement") or p.get("transportation_expenses")
            if rental and isinstance(rental, dict):
                result["rental_reimbursement"] = rental
            return json.dumps(result)
        return json.dumps({
            "valid": False,
            "status": status,
            "message": "Policy not found or inactive",
        })
    return json.dumps({"valid": False, "message": "Policy not found or inactive"})
