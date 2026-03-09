"""Human review handback orchestrator: processes claims returned from human review.

Runs the handback crew to parse reviewer decision, update claim, then invokes
the main workflow for routing to settlement, subrogation, etc.
"""

import json

from claim_agent.context import ClaimContext
from claim_agent.crews.human_review_handback_crew import create_human_review_handback_crew
from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.models.claim import ClaimInput
from claim_agent.workflow.helpers import _kickoff_with_retry
from claim_agent.workflow.orchestrator import run_claim_workflow


def run_handback_workflow(
    claim_id: str,
    reviewer_decision: dict | None = None,
    *,
    actor_id: str | None = None,
    ctx: ClaimContext | None = None,
) -> dict:
    """Process a claim returned from human review with a decision.

    1. Runs the handback crew to parse reviewer decision and update the claim.
    2. Re-fetches the claim and runs the main workflow to route to next step
       (settlement, denial, subrogation).

    Args:
        claim_id: The claim ID.
        reviewer_decision: Optional dict with confirmed_claim_type, confirmed_payout, notes.
        actor_id: Actor performing the handback.
        ctx: ClaimContext. When None, built from defaults.

    Returns:
        dict from run_claim_workflow (claim_id, claim_type, status, etc.).
    """
    if ctx is None:
        ctx = ClaimContext.from_defaults()

    decision_str = json.dumps(reviewer_decision or {})
    crew = create_human_review_handback_crew(ctx.llm)
    _kickoff_with_retry(crew, {
        "claim_id": claim_id,
        "reviewer_decision": decision_str,
    })

    # Re-fetch claim after handback crew has applied updates
    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        from claim_agent.exceptions import ClaimNotFoundError
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    claim_data = claim_data_from_row(claim)
    ClaimInput.model_validate(claim_data)

    return run_claim_workflow(
        claim_data,
        existing_claim_id=claim_id,
        actor_id=actor_id,
        ctx=ctx,
    )
