"""Supplemental workflow orchestration: run_supplemental_workflow entry point.

Standalone workflow for supplemental damage reports on existing partial loss
claims (invoked separately from the main claim pipeline). Flow: intake
(validate + retrieve original) -> verify damage -> adjust estimate ->
update authorization. California CCR 2695.8 requires prompt inspection
and authorization of supplemental payment when additional damage is discovered.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claim_agent.config.llm import get_llm
from claim_agent.context import ClaimContext
from claim_agent.crews.supplemental_crew import create_supplemental_crew
from claim_agent.db.constants import SUPPLEMENTABLE_STATUSES
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.supplemental import SupplementalInput
from claim_agent.observability import get_logger
from claim_agent.workflow.helpers import _kickoff_with_retry

logger = get_logger(__name__)


def _get_latest_workflow_output(repo: Any, claim_id: str) -> str | None:
    """Retrieve the most recent workflow_output for a claim."""
    runs = repo.get_workflow_runs(claim_id, limit=1)
    return runs[0]["workflow_output"] if runs else None


def run_supplemental_workflow(
    supplemental_data: dict[str, Any],
    *,
    llm: Any | None = None,
    ctx: ClaimContext | None = None,
    state: str = "California",
) -> dict[str, Any]:
    """Run the supplemental workflow for additional damage discovered during repair.

    Args:
        supplemental_data: Dict with claim_id, supplemental_damage_description,
            and optional reported_by.
        llm: Optional LLM instance.
        ctx: Dependency-injection context.
        state: State jurisdiction for compliance (default California).

    Returns:
        Dict with claim_id, status, supplemental_amount, combined_insurance_pays,
        workflow_output, and summary.
    """
    start_time = time.time()

    supplemental_input = SupplementalInput.model_validate(supplemental_data)

    _llm = llm or (ctx.llm if ctx else None) or get_llm()
    if ctx is None:
        ctx = ClaimContext.from_defaults(llm=_llm)
    elif ctx.llm is None or llm is not None:
        ctx = ClaimContext(
            repo=ctx.repo,
            adjuster_service=ctx.adjuster_service,
            adapters=ctx.adapters,
            metrics=ctx.metrics,
            llm=_llm,
        )
    repo = ctx.repo

    claim = repo.get_claim(supplemental_input.claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {supplemental_input.claim_id}")

    claim_type = claim.get("claim_type")
    if claim_type != "partial_loss":
        raise ValueError(
            f"Supplemental workflow only applies to partial_loss claims. "
            f"Claim {supplemental_input.claim_id} has claim_type={claim_type!r}."
        )

    claim_status = claim.get("status")
    if claim_status not in SUPPLEMENTABLE_STATUSES:
        raise ValueError(
            f"Claim {supplemental_input.claim_id} cannot receive supplemental in status {claim_status!r}. "
            f"Allowed statuses: {', '.join(SUPPLEMENTABLE_STATUSES)}."
        )

    logger.info(
        "Starting supplemental workflow",
        extra={
            "claim_id": supplemental_input.claim_id,
            "reported_by": supplemental_input.reported_by,
        },
    )

    claim_data_for_crew = {
        "claim_id": claim.get("id"),
        "policy_number": claim.get("policy_number"),
        "vin": claim.get("vin"),
        "vehicle_year": claim.get("vehicle_year"),
        "vehicle_make": claim.get("vehicle_make"),
        "vehicle_model": claim.get("vehicle_model"),
        "incident_date": claim.get("incident_date"),
        "incident_description": claim.get("incident_description"),
        "damage_description": claim.get("damage_description"),
        "estimated_damage": claim.get("estimated_damage"),
        "payout_amount": claim.get("payout_amount"),
        "claim_type": claim.get("claim_type"),
        "status": claim.get("status"),
    }

    original_workflow_output = _get_latest_workflow_output(repo, supplemental_input.claim_id)

    crew_inputs = {
        "claim_data": json.dumps(claim_data_for_crew),
        "supplemental_data": json.dumps(supplemental_input.model_dump(mode="json")),
        "original_workflow_output": original_workflow_output or "No prior workflow output available.",
    }

    supplemental_crew = create_supplemental_crew(_llm, state=state)
    result = _kickoff_with_retry(supplemental_crew, crew_inputs)

    workflow_output = str(
        getattr(result, "raw", None)
        or getattr(result, "output", None)
        or str(result)
    )

    supplemental_amount = _extract_supplemental_amount(workflow_output)
    combined_insurance_pays = _extract_combined_insurance_pays(workflow_output)

    if supplemental_amount is not None or combined_insurance_pays is not None:
        repo.update_claim_status(
            supplemental_input.claim_id,
            claim_status,
            details=workflow_output[:500],
            payout_amount=combined_insurance_pays or supplemental_amount,
        )

    repo.save_workflow_result(
        supplemental_input.claim_id,
        "supplemental",
        json.dumps(supplemental_input.model_dump(mode="json")),
        workflow_output,
    )

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Supplemental workflow completed",
        extra={
            "claim_id": supplemental_input.claim_id,
            "supplemental_amount": supplemental_amount,
            "elapsed_ms": elapsed_ms,
        },
    )

    return {
        "claim_id": supplemental_input.claim_id,
        "status": claim_status,
        "supplemental_amount": supplemental_amount,
        "combined_insurance_pays": combined_insurance_pays,
        "workflow_output": workflow_output,
        "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
    }


def _extract_supplemental_amount(workflow_output: str) -> float | None:
    """Best-effort extraction of supplemental amount from crew output."""
    import re

    patterns = [
        r"supplemental_total[:\s]*\$?([\d,]+\.?\d*)",
        r"supplemental_insurance_pays[:\s]*\$?([\d,]+\.?\d*)",
        r"supplemental_amount[:\s]*\$?([\d,]+\.?\d*)",
    ]
    for pattern in patterns:
        m = re.search(pattern, workflow_output, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def _extract_combined_insurance_pays(workflow_output: str) -> float | None:
    """Best-effort extraction of combined insurance pays from crew output."""
    import re

    m = re.search(
        r"combined_insurance_pays[:\s]*\$?([\d,]+\.?\d*)",
        workflow_output,
        re.IGNORECASE,
    )
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None
