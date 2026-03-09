"""Human review handback orchestrator: processes claims returned from human review.

Runs the handback crew to parse reviewer decision, update claim, then invokes
the main workflow for routing to settlement, subrogation, etc.
"""

import json

from claim_agent.context import ClaimContext
from claim_agent.crews.human_review_handback_crew import create_human_review_handback_crew
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.db.constants import STATUS_PROCESSING
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.utils.sanitization import sanitize_note
from claim_agent.workflow.helpers import _kickoff_with_retry

def _sanitize_reviewer_decision(decision: dict | None) -> dict:
    """Return a sanitized copy of the reviewer decision dict.

    Free-text fields (notes, confirmed_claim_type) are stripped of control
    characters and prompt-injection patterns before the dict is serialized
    and injected into an LLM task description.
    """
    if not decision:
        return {}
    sanitized: dict = {}
    for key, value in decision.items():
        if key in ("notes", "confirmed_claim_type"):
            sanitized[key] = sanitize_note(value) if value is not None else None
        else:
            sanitized[key] = value
    return sanitized


def run_handback_workflow(
    claim_id: str,
    reviewer_decision: dict | None = None,
    *,
    actor_id: str | None = None,
    ctx: ClaimContext | None = None,
) -> dict:
    """Process a claim returned from human review with a decision.

    1. Runs the handback crew to parse reviewer decision and update the claim.
    2. Validates that the crew transitioned the claim to processing status.
    3. Re-fetches the claim and runs the main workflow to route to next step
       (settlement, denial, subrogation).

    Args:
        claim_id: The claim ID.
        reviewer_decision: Optional dict with confirmed_claim_type, confirmed_payout, notes.
        actor_id: Actor performing the handback.
        ctx: ClaimContext. When None, built from defaults.

    Returns:
        dict from run_claim_workflow (claim_id, claim_type, status, etc.).

    Raises:
        ClaimNotFoundError: If the claim does not exist.
        ValueError: If the handback crew failed to transition the claim to processing status.
    """
    if ctx is None:
        ctx = ClaimContext.from_defaults()

    safe_decision = _sanitize_reviewer_decision(reviewer_decision)
    decision_str = json.dumps(safe_decision)
    crew = create_human_review_handback_crew(ctx.llm)
    _kickoff_with_retry(crew, {
        "claim_id": claim_id,
        "reviewer_decision": decision_str,
        "actor_id": actor_id or "handback_crew",
    })

    # Re-fetch claim after handback crew has applied updates
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    # Guard: ensure the crew successfully transitioned the claim to processing.
    # If apply_reviewer_decision was not called, the claim remains in needs_review
    # and run_claim_workflow would execute against an unexpected status.
    if claim.get("status") != STATUS_PROCESSING:
        raise ValueError(
            f"Handback crew did not transition claim {claim_id} to processing status "
            f"(current status: {claim.get('status')!r}). Cannot continue workflow."
        )

    claim_data = claim_data_from_row(claim)

    from claim_agent.workflow.orchestrator import run_claim_workflow

    return run_claim_workflow(
        claim_data,
        existing_claim_id=claim_id,
        actor_id=actor_id,
        ctx=ctx,
    )
