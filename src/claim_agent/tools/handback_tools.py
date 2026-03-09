"""Human review handback tools: parse reviewer decision, update claim, route to next step."""

import json

from crewai.tools import tool

import logging
import math

from claim_agent.db.repository import ClaimRepository
from claim_agent.db.constants import STATUS_PROCESSING
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.claim import ClaimType
from claim_agent.utils.sanitization import MAX_PAYOUT, sanitize_note

# Handback-supported claim types (excludes REOPENED which is workflow-specific)
VALID_CLAIM_TYPES = frozenset(
    ct.value for ct in ClaimType if ct != ClaimType.REOPENED
)

logger = logging.getLogger(__name__)


def _get_repo():
    """Get repository instance for handback tools."""
    return ClaimRepository()


def _try_parse_escalation(s: str) -> dict | None:
    """Try to extract escalation JSON from workflow output string.

    First attempts to parse the whole string as JSON, then scans backwards
    for the last JSON object in the string.
    """
    # Try parsing whole string first
    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict) and (
            "escalation" in parsed or "mid_workflow" in parsed or "escalation_reasons" in parsed
        ):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    # Try finding the last JSON object in the string (e.g. after narrative text)
    last_brace = s.rfind("{")
    while last_brace >= 0:
        try:
            parsed = json.loads(s[last_brace:])
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
        last_brace = s.rfind("{", 0, last_brace)
    return None


@tool("Get Escalation Context")
def get_escalation_context(claim_id: str) -> str:
    """Retrieve escalation context for a claim returned from human review.

    Fetches the claim record and latest workflow run to extract escalation
    stage, reasons, and prior workflow output. Use this to determine where
    the claim was when it was escalated and what the reviewer was asked to decide.

    Args:
        claim_id: The claim ID.

    Returns:
        JSON with claim_id, claim_type, status, payout_amount, escalation_stage,
        escalation_reasons, mid_workflow (bool), and prior_workflow_output (truncated).
    """
    repo = _get_repo()
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    runs = repo.get_workflow_runs(claim_id, limit=1)
    workflow_output = ""
    escalation_stage = None
    escalation_reasons = []
    mid_workflow = False

    if runs:
        run = runs[0]
        workflow_output = run.get("workflow_output") or ""

        parsed = _try_parse_escalation(workflow_output)
        if parsed:
            mid_workflow = parsed.get("mid_workflow", False)
            escalation_stage = parsed.get("stage")
            reason = parsed.get("reason")
            if reason:
                escalation_reasons.append(reason)
            indicators = parsed.get("indicators", [])
            escalation_reasons.extend(indicators)
            for r in parsed.get("escalation_reasons", []):
                if r and r not in escalation_reasons:
                    escalation_reasons.append(r)
            if "low_router_confidence" in escalation_reasons and not escalation_stage:
                escalation_stage = "router"
        elif "escalation" in workflow_output.lower() or "mid_workflow" in workflow_output.lower():
            mid_workflow = True

    return json.dumps({
        "claim_id": claim_id,
        "claim_type": claim.get("claim_type"),
        "status": claim.get("status"),
        "payout_amount": claim.get("payout_amount"),
        "escalation_stage": escalation_stage,
        "escalation_reasons": escalation_reasons,
        "mid_workflow": mid_workflow,
        "prior_workflow_output": workflow_output[:2000] + "..." if len(workflow_output) > 2000 else workflow_output,
    })


@tool("Apply Reviewer Decision")
def apply_reviewer_decision(
    claim_id: str,
    confirmed_claim_type: str = "",
    confirmed_payout: str = "",
    actor_id: str = "handback_crew",
) -> str:
    """Apply reviewer decision overrides to the claim before routing to next step.

    Updates the claim with confirmed_claim_type and/or confirmed_payout when
    the reviewer has explicitly confirmed or overridden the classification or
    payout amount. Sets status to processing so the workflow can continue.

    Args:
        claim_id: The claim ID.
        confirmed_claim_type: Reviewer-confirmed claim type (e.g. partial_loss, total_loss).
            Must be one of: new, duplicate, total_loss, partial_loss, bodily_injury, fraud.
        confirmed_payout: Reviewer-confirmed payout amount as string (e.g. "12500.00").
        actor_id: Actor performing the handback (for audit).

    Returns:
        JSON with claim_id, updated_claim_type, updated_payout_amount, status.
    """
    repo = _get_repo()
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    claim_type = claim.get("claim_type")
    payout_amount = claim.get("payout_amount")

    ct_str = str(confirmed_claim_type).strip().lower() if confirmed_claim_type else ""
    if ct_str and ct_str in VALID_CLAIM_TYPES:
        claim_type = ct_str
    elif ct_str:
        logger.warning(
            "Invalid confirmed_claim_type %r for claim %s; keeping existing %r",
            confirmed_claim_type,
            claim_id,
            claim_type,
        )

    if confirmed_payout and str(confirmed_payout).strip():
        try:
            val = float(confirmed_payout)
            if math.isfinite(val) and 0 <= val <= MAX_PAYOUT:
                payout_amount = val
        except (ValueError, TypeError):
            pass

    repo.update_claim_status(
        claim_id,
        STATUS_PROCESSING,
        claim_type=claim_type,
        payout_amount=payout_amount,
        details="Handback: reviewer decision applied",
        actor_id=actor_id,
    )

    return json.dumps({
        "claim_id": claim_id,
        "updated_claim_type": claim_type,
        "updated_payout_amount": payout_amount,
        "status": STATUS_PROCESSING,
    })


@tool("Parse Reviewer Decision")
def parse_reviewer_decision(
    reviewer_notes: str,
    structured_decision: str = "{}",
) -> str:
    """Parse reviewer decision from notes or structured input.

    Extracts confirmed_claim_type, confirmed_payout, and routing intent from
    free-form reviewer notes or a structured JSON decision. Use when the
    reviewer provides narrative feedback that needs to be interpreted.

    Args:
        reviewer_notes: Free-form text from the reviewer (e.g. "Confirmed partial loss, approve $8500").
        structured_decision: Optional JSON string with keys: confirmed_claim_type, confirmed_payout, notes.

    Returns:
        JSON with confirmed_claim_type, confirmed_payout, next_step (settlement|denial|subrogation|workflow),
        and reasoning.
    """
    result = {
        "confirmed_claim_type": None,
        "confirmed_payout": None,
        "next_step": "workflow",
        "reasoning": "",
    }

    if structured_decision and str(structured_decision).strip():
        try:
            data = json.loads(structured_decision)
            if isinstance(data, dict):
                result["confirmed_claim_type"] = data.get("confirmed_claim_type")
                result["confirmed_payout"] = data.get("confirmed_payout")
                result["next_step"] = data.get("next_step", "workflow")
        except (json.JSONDecodeError, TypeError):
            pass

    # If structured didn't provide values, leave for LLM to infer from notes
    if reviewer_notes and str(reviewer_notes).strip():
        safe_notes = sanitize_note(reviewer_notes)
        result["reasoning"] = f"Reviewer notes to interpret: {safe_notes[:500]}"

    return json.dumps(result)
