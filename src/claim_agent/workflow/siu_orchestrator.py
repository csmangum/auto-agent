"""SIU investigation workflow orchestration: run_siu_investigation entry point.

Runs the SIU Investigation crew on claims under Special Investigations Unit
review. Performs document verification, records investigation, and case
management including state fraud bureau filing.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claim_agent.config.llm import get_llm
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.context import ClaimContext
from claim_agent.crews.siu_crew import create_siu_crew
from claim_agent.db.constants import SIU_INVESTIGATION_STATUSES
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.observability import get_logger
from claim_agent.workflow.helpers import _kickoff_with_retry

logger = get_logger(__name__)


def run_siu_investigation(
    claim_id: str,
    *,
    llm: LLMProtocol | None = None,
    ctx: ClaimContext | None = None,
) -> dict[str, Any]:
    """Run the SIU investigation workflow for a claim.

    Claim must have status under_investigation or fraud_suspected.
    Creates SIU case via adapter if not already present (e.g., manual escalation).

    Args:
        claim_id: Claim ID.
        llm: Optional LLM instance.
        ctx: Dependency-injection context.

    Returns:
        Dict with claim_id, workflow_output, and summary.

    Raises:
        ClaimNotFoundError: If claim does not exist.
        ValueError: If claim status is not under_investigation or fraud_suspected.
    """
    start_time = time.time()

    if ctx is None:
        ctx = ClaimContext.from_defaults(llm=None)
    repo = ctx.repo

    claim = repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    status = claim.get("status")
    if status not in SIU_INVESTIGATION_STATUSES:
        raise ValueError(
            f"SIU investigation requires status under_investigation or fraud_suspected; got {status!r}"
        )

    siu_case_id = claim.get("siu_case_id")
    if not siu_case_id:
        case_id = ctx.adapters.siu.create_case(claim_id, indicators=[])
        repo.update_claim_siu_case_id(claim_id, case_id, actor_id="system")
        siu_case_id = case_id
        claim = repo.get_claim(claim_id) or claim

    claim_data_for_crew = {
        "id": claim.get("id"),
        "claim_id": claim.get("id"),
        "siu_case_id": siu_case_id,
        "policy_number": claim.get("policy_number"),
        "vin": claim.get("vin"),
        "vehicle_year": claim.get("vehicle_year"),
        "vehicle_make": claim.get("vehicle_make"),
        "vehicle_model": claim.get("vehicle_model"),
        "incident_date": claim.get("incident_date"),
        "incident_description": claim.get("incident_description"),
        "damage_description": claim.get("damage_description"),
        "status": claim.get("status"),
        "claim_type": claim.get("claim_type"),
        "state": "California",
    }

    crew_inputs = {"claim_data": json.dumps(claim_data_for_crew)}

    _llm = llm or get_llm()
    siu_crew = create_siu_crew(llm=_llm)
    result = _kickoff_with_retry(siu_crew, crew_inputs)

    workflow_output = str(
        getattr(result, "raw", None)
        or getattr(result, "output", None)
        or str(result)
    )

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "SIU investigation workflow completed",
        extra={"claim_id": claim_id, "elapsed_ms": elapsed_ms},
    )

    return {
        "claim_id": claim_id,
        "workflow_output": workflow_output,
        "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
    }
