"""Claim status transition tools.

Provides a controlled tool for closing claims. Only allows transition to
the ``closed`` status to limit blast radius compared to a generic
status-update tool.
"""

import json
import logging

from crewai.tools import tool

from claim_agent.db.constants import STATUS_CLOSED
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.utils.sanitization import sanitize_note

logger = logging.getLogger(__name__)


@tool("Close Claim")
def close_claim(claim_id: str, reason: str) -> str:
    """Transition a claim's status to closed.

    Use only when the claim workflow is fully complete: settlement processed,
    payments distributed, and no outstanding follow-ups remain. The reason
    is recorded in the audit log.

    Args:
        claim_id: The claim ID to close.
        reason: Brief explanation of why the claim is being closed.

    Returns:
        JSON with success (bool) and message.
    """
    claim_id = str(claim_id).strip()
    reason = str(reason).strip()
    if not claim_id:
        return json.dumps({"success": False, "message": "claim_id is required"})
    if not reason:
        return json.dumps({"success": False, "message": "reason is required"})
    reason = sanitize_note(reason)
    try:
        repo = ClaimRepository()
        claim = repo.get_claim(claim_id)
        if claim is None:
            return json.dumps({"success": False, "message": f"Claim not found: {claim_id}"})
        if claim.get("status") == STATUS_CLOSED:
            return json.dumps({"success": True, "message": f"Claim {claim_id} already closed"})
        payout = claim.get("payout_amount")
        if payout is None:
            payout = 0.0
        repo.update_claim_status(
            claim_id,
            STATUS_CLOSED,
            details=reason,
            payout_amount=payout,
            actor_id="After-Action Status",
        )
        return json.dumps({"success": True, "message": f"Claim {claim_id} closed"})
    except ClaimNotFoundError:
        return json.dumps({"success": False, "message": f"Claim not found: {claim_id}"})
    except Exception:
        logger.exception("Unexpected error closing claim %s", claim_id)
        return json.dumps({"success": False, "message": "An unexpected error occurred while closing the claim"})
