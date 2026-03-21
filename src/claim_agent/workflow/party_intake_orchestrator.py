"""Orchestration entry point for witness/attorney party intake crew."""

from __future__ import annotations

import json
import time
from typing import Any

from claim_agent.config.llm import get_llm
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.context import ClaimContext
from claim_agent.crews.party_intake_crew import create_party_intake_crew
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.observability import get_logger
from claim_agent.utils.llm_data_minimization import minimize_claim_data_for_crew
from claim_agent.workflow.helpers import _kickoff_with_retry

logger = get_logger(__name__)


def run_party_intake_workflow(
    claim_id: str,
    focus: str,
    *,
    llm: LLMProtocol | None = None,
    ctx: ClaimContext | None = None,
) -> dict[str, Any]:
    """Run witness + attorney party intake for a claim.

    Args:
        claim_id: Claim ID.
        focus: Adjuster instructions (e.g. witness names, statement text, LOP received).
        llm: Optional LLM.
        ctx: Optional claim context (repo, etc.).

    Returns:
        Dict with claim_id, workflow_output, summary.
    """
    start_time = time.time()
    if ctx is None:
        ctx = ClaimContext.from_defaults(llm=None)
    repo = ctx.repo

    claim = repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    parties = repo.get_claim_parties(claim_id)
    base = {
        "id": claim.get("id"),
        "claim_id": claim.get("id"),
        "policy_number": claim.get("policy_number"),
        "vin": claim.get("vin"),
        "status": claim.get("status"),
        "claim_type": claim.get("claim_type"),
        "incident_description": claim.get("incident_description"),
        "damage_description": claim.get("damage_description"),
        "parties": parties,
    }
    claim_data_for_crew = minimize_claim_data_for_crew(base, "party_intake")

    notes = repo.get_notes(claim_id)
    claim_notes = (
        "\n".join(f"- [{n.get('actor_id')}] {n.get('note', '')}" for n in notes)
        if notes
        else "No prior notes."
    )

    crew_inputs = {
        "claim_data": json.dumps(claim_data_for_crew, default=str),
        "focus": focus,
        "claim_notes": claim_notes,
    }

    _llm = llm or get_llm()
    crew = create_party_intake_crew(llm=_llm)
    result = _kickoff_with_retry(crew, crew_inputs)

    workflow_output = str(
        getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    )

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Party intake workflow completed",
        extra={"claim_id": claim_id, "elapsed_ms": elapsed_ms},
    )

    return {
        "claim_id": claim_id,
        "workflow_output": workflow_output,
        "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
    }
