"""Follow-up workflow orchestration: run_follow_up_workflow entry point.

Handles structured outreach to claimants, policyholders, repair shops, and other
stakeholders. Integrates with pending_info when adjuster requests more info.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claim_agent.config.llm import get_llm
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.context import ClaimContext
from claim_agent.crews.follow_up_crew import create_follow_up_crew
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.observability import get_logger
from claim_agent.utils.llm_data_minimization import minimize_claim_data_for_crew
from claim_agent.workflow.helpers import _kickoff_with_retry

logger = get_logger(__name__)


def run_follow_up_workflow(
    claim_id: str,
    task: str,
    *,
    llm: LLMProtocol | None = None,
    ctx: ClaimContext | None = None,
    user_response: str | None = None,
) -> dict[str, Any]:
    """Run the follow-up workflow for a claim.

    Args:
        claim_id: Claim ID.
        task: Description of the follow-up task (e.g., "Gather photos of damage from claimant").
        llm: Optional LLM instance.
        ctx: Dependency-injection context.
        user_response: Optional response from user (when recording a response in same run).

    Returns:
        Dict with claim_id, workflow_output, and summary.
    """
    start_time = time.time()

    if ctx is None:
        ctx = ClaimContext.from_defaults(llm=None)
    repo = ctx.repo

    claim = repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    claim_data_for_crew = minimize_claim_data_for_crew(
        {
            "id": claim.get("id"),
            "policy_number": claim.get("policy_number"),
            "vin": claim.get("vin"),
            "status": claim.get("status"),
            "claim_type": claim.get("claim_type"),
            "incident_description": claim.get("incident_description"),
            "damage_description": claim.get("damage_description"),
        },
        "follow_up",
    )

    notes = repo.get_notes(claim_id)
    claim_notes = "\n".join(
        f"- [{n.get('actor_id')}] {n.get('note', '')}" for n in notes
    ) if notes else "No prior notes."

    crew_inputs = {
        "claim_data": json.dumps(claim_data_for_crew),
        "task": task,
        "claim_notes": claim_notes,
    }
    crew_inputs["user_response"] = user_response if user_response else "No response provided yet."

    _llm = llm or get_llm()
    follow_up_crew = create_follow_up_crew(llm=_llm)
    result = _kickoff_with_retry(follow_up_crew, crew_inputs)

    workflow_output = str(
        getattr(result, "raw", None)
        or getattr(result, "output", None)
        or str(result)
    )

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Follow-up workflow completed",
        extra={"claim_id": claim_id, "elapsed_ms": elapsed_ms},
    )

    return {
        "claim_id": claim_id,
        "workflow_output": workflow_output,
        "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
    }
