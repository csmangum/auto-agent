"""Dispute workflow orchestration: run_dispute_workflow entry point.

Standalone workflow for policyholder disputes on existing claims (invoked
separately from the main claim pipeline). Flow: intake (retrieve claim +
classify dispute) -> policy/compliance analysis -> resolution. Resolution
either auto-resolves (valuation, repair estimate, deductible) or escalates
(liability / complex cases) to human adjusters. Final status is
dispute_resolved or needs_review accordingly.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from claim_agent.config.llm import get_llm
from claim_agent.context import ClaimContext
from claim_agent.crews.dispute_crew import create_dispute_crew
from claim_agent.db.constants import (
    STATUS_DISPUTED,
    STATUS_DISPUTE_RESOLVED,
    STATUS_NEEDS_REVIEW,
)
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.dispute import DisputeInput, DisputeType
from claim_agent.observability import get_logger
from claim_agent.workflow.helpers import _kickoff_with_retry

logger = get_logger(__name__)

# Regex patterns for extracting adjusted amount from crew output (fallback when no structured block)
_ADJUSTED_AMOUNT_PATTERNS = (
    re.compile(r"adjusted[_ ]amount[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"new[_ ]amount[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
    re.compile(r"revised[_ ](?:payout|amount)[:\s]*\$?([\d,]+\.?\d*)", re.IGNORECASE),
)


def run_dispute_workflow(
    dispute_data: dict[str, Any],
    *,
    llm: Any | None = None,
    ctx: ClaimContext | None = None,
) -> dict[str, Any]:
    """Run the dispute resolution workflow for a policyholder dispute.

    Args:
        dispute_data: Dict with claim_id, dispute_type, dispute_description,
            and optional policyholder_evidence.
        llm: Optional LLM instance.
        ctx: Dependency-injection context.

    Returns:
        Dict with claim_id, dispute_type, resolution_type, status,
        workflow_output, and optional adjusted_amount.
    """
    start_time = time.time()

    dispute_input = DisputeInput.model_validate(dispute_data)

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

    claim = repo.get_claim(dispute_input.claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {dispute_input.claim_id}")

    logger.info(
        "Starting dispute workflow",
        extra={
            "claim_id": dispute_input.claim_id,
            "dispute_type": dispute_input.dispute_type.value,
        },
    )

    repo.update_claim_status(
        dispute_input.claim_id,
        STATUS_DISPUTED,
        details=f"Dispute filed: {dispute_input.dispute_type.value}",
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

    original_workflow_output = _get_latest_workflow_output(repo, dispute_input.claim_id)

    crew_inputs = {
        "claim_data": json.dumps(claim_data_for_crew),
        "dispute_data": json.dumps(dispute_input.model_dump(mode="json")),
        "original_workflow_output": original_workflow_output or "No prior workflow output available.",
    }

    dispute_crew = create_dispute_crew(_llm)
    result = _kickoff_with_retry(dispute_crew, crew_inputs)

    workflow_output = str(
        getattr(result, "raw", None)
        or getattr(result, "output", None)
        or str(result)
    )

    parsed = _parse_structured_resolution(workflow_output)
    if parsed is not None:
        resolution_type, adjusted_amount = parsed
    else:
        resolution_type = _infer_resolution_type(workflow_output, dispute_input.dispute_type)
        adjusted_amount = _extract_adjusted_amount(workflow_output)

    if resolution_type == "auto_resolved":
        final_status = STATUS_DISPUTE_RESOLVED
        repo.update_claim_status(
            dispute_input.claim_id,
            final_status,
            details=workflow_output[:500],
            payout_amount=adjusted_amount,
        )
    else:
        final_status = STATUS_NEEDS_REVIEW
        repo.update_claim_status(
            dispute_input.claim_id,
            final_status,
            details=f"Dispute escalated: {workflow_output[:400]}",
        )

    repo.save_workflow_result(
        dispute_input.claim_id,
        f"dispute:{dispute_input.dispute_type.value}",
        json.dumps(dispute_input.model_dump(mode="json")),
        workflow_output,
    )

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Dispute workflow completed",
        extra={
            "claim_id": dispute_input.claim_id,
            "dispute_type": dispute_input.dispute_type.value,
            "resolution_type": resolution_type,
            "status": final_status,
            "elapsed_ms": elapsed_ms,
        },
    )

    return {
        "claim_id": dispute_input.claim_id,
        "dispute_type": dispute_input.dispute_type.value,
        "resolution_type": resolution_type,
        "status": final_status,
        "workflow_output": workflow_output,
        "adjusted_amount": adjusted_amount,
        "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
    }


def _parse_structured_resolution(workflow_output: str) -> tuple[str, float | None] | None:
    """Try to parse resolution_type and adjusted_amount from a JSON block in the output.

    Looks for ```json ... ``` or ``` ... ``` containing resolution_type (and
    optionally adjusted_amount). Returns (resolution_type, adjusted_amount) or
    None if no valid structured block is found.
    """
    # Code block: ```json ... ``` or ``` ... ``` (content may span lines)
    code_block = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.DOTALL)
    match = code_block.search(workflow_output)
    if match:
        blob = match.group(1).strip()
        try:
            data = json.loads(blob)
            if not isinstance(data, dict):
                return None
            rt = data.get("resolution_type")
            if rt not in ("auto_resolved", "escalated"):
                return None
            adj = data.get("adjusted_amount")
            if adj is not None:
                try:
                    adj = float(adj)
                except (TypeError, ValueError):
                    adj = None
            return (rt, adj)
        except json.JSONDecodeError:
            pass
    return None


def _get_latest_workflow_output(repo: Any, claim_id: str) -> str | None:
    """Retrieve the most recent workflow_output for a claim."""
    try:
        from claim_agent.db.database import get_connection
        with get_connection(repo._db_path) as conn:
            row = conn.execute(
                "SELECT workflow_output FROM workflow_runs "
                "WHERE claim_id = ? ORDER BY created_at DESC LIMIT 1",
                (claim_id,),
            ).fetchone()
        return row["workflow_output"] if row else None
    except Exception as exc:
        logger.debug("Could not fetch workflow output for %s: %s", claim_id, exc)
        return None


def _infer_resolution_type(workflow_output: str, dispute_type: DisputeType) -> str:
    """Determine resolution type from crew output text."""
    lower = workflow_output.lower()
    if "auto_resolved" in lower or "auto-resolved" in lower or "auto resolved" in lower:
        return "auto_resolved"
    if "escalated" in lower or "escalation" in lower or "human review" in lower:
        return "escalated"
    from claim_agent.models.dispute import AUTO_RESOLVABLE_DISPUTE_TYPES
    if dispute_type in AUTO_RESOLVABLE_DISPUTE_TYPES:
        return "auto_resolved"
    return "escalated"


def _extract_adjusted_amount(workflow_output: str) -> float | None:
    """Best-effort extraction of adjusted amount from crew output."""
    lower = workflow_output.lower()
    for pattern in _ADJUSTED_AMOUNT_PATTERNS:
        match = pattern.search(lower)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None
