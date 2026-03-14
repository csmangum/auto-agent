"""SIU investigation orchestration: run_siu_investigation entry point.

Standalone workflow for claims under SIU investigation (status: under_investigation).
Performs document verification, records investigation, and case management including
state fraud bureau filing when required.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claim_agent.config.llm import get_llm
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.context import ClaimContext
from claim_agent.crews.siu_crew import create_siu_crew
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.observability import get_logger
from claim_agent.workflow.helpers import _kickoff_with_retry

logger = get_logger(__name__)

SIU_ELIGIBLE_STATUSES = ("under_investigation", "fraud_suspected")


def run_siu_investigation(
    claim_id: str,
    *,
    llm: LLMProtocol | None = None,
    ctx: ClaimContext | None = None,
    state: str = "California",
) -> dict[str, Any]:
    """Run the SIU investigation crew for a claim under investigation.

    Args:
        claim_id: The claim ID to investigate.
        llm: Optional LLM instance.
        ctx: Dependency-injection context.
        state: State jurisdiction for fraud bureau filing (default California).

    Returns:
        Dict with claim_id, status, workflow_output, siu_case_id, summary.

    Raises:
        ClaimNotFoundError: If the claim does not exist.
        ValueError: If claim is not eligible for SIU investigation.
    """
    start_time = time.time()

    if ctx is None:
        ctx = ClaimContext.from_defaults(llm=None)
    repo = ctx.repo

    claim = repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    claim_status = claim.get("status")
    if claim_status not in SIU_ELIGIBLE_STATUSES:
        raise ValueError(
            f"Claim {claim_id} is not eligible for SIU investigation. "
            f"Status must be under_investigation or fraud_suspected, got {claim_status!r}."
        )

    siu_case_id = claim.get("siu_case_id")
    if not siu_case_id:
        from claim_agent.adapters.registry import get_siu_adapter

        adapter = ctx.adapters.siu if ctx else get_siu_adapter()
        try:
            indicators = ["manual_escalation"]
            workflow_runs = repo.get_workflow_runs(claim_id, limit=5)
            for run in workflow_runs:
                wo = run.get("workflow_output") or ""
                if "fraud" in wo.lower() or "staged" in wo.lower():
                    indicators = ["fraud_indicators_from_workflow"]
                    break
            siu_case_id = adapter.create_case(claim_id, indicators)
            repo.update_claim_siu_case_id(claim_id, siu_case_id)
        except NotImplementedError:
            raise ValueError(
                f"Claim {claim_id} has no siu_case_id and SIU case creation is not implemented. "
                "Escalate via fraud workflow first to create a case, or use an adapter that supports create_case."
            )

    _llm = llm or (ctx.llm if ctx else None) or get_llm()
    if ctx.llm is None or llm is not None:
        ctx = ClaimContext(
            repo=ctx.repo,
            adjuster_service=ctx.adjuster_service,
            adapters=ctx.adapters,
            metrics=ctx.metrics,
            llm=_llm,
        )

    logger.info(
        "Starting SIU investigation",
        extra={"claim_id": claim_id, "siu_case_id": siu_case_id},
    )

    claim_data_for_crew = {
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
        "estimated_damage": claim.get("estimated_damage"),
        "claim_type": claim.get("claim_type"),
        "status": claim.get("status"),
        "state": state,
    }

    crew_inputs = {
        "claim_data": json.dumps(claim_data_for_crew),
    }

    crew = create_siu_crew(_llm)
    result = _kickoff_with_retry(crew, crew_inputs)

    workflow_output = str(
        getattr(result, "raw", None)
        or getattr(result, "output", None)
        or str(result)
    )

    repo.save_workflow_result(claim_id, "siu_investigation", json.dumps({"siu_case_id": siu_case_id}), workflow_output)

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "SIU investigation completed",
        extra={"claim_id": claim_id, "siu_case_id": siu_case_id, "elapsed_ms": elapsed_ms},
    )

    return {
        "claim_id": claim_id,
        "status": claim_status,
        "siu_case_id": siu_case_id,
        "workflow_output": workflow_output,
        "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
    }
