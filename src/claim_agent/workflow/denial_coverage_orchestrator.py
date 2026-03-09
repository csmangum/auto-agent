"""Denial and coverage dispute workflow orchestration.

Standalone workflow for denied claims. Flow: review denial reason ->
verify coverage/exclusions -> generate denial letter or route to appeal.
Integration: STATUS_DENIED; triggered via POST /claims/{id}/denial-coverage.
"""

from __future__ import annotations

import json
import time
from typing import Any

from claim_agent.config.llm import get_llm
from claim_agent.context import ClaimContext
from claim_agent.crews.denial_coverage_crew import create_denial_coverage_crew
from claim_agent.db.constants import STATUS_DENIED, STATUS_NEEDS_REVIEW
from claim_agent.exceptions import ClaimNotFoundError, MidWorkflowEscalation
from claim_agent.models.denial import DenialInput
from claim_agent.observability import get_logger
from claim_agent.utils.sanitization import sanitize_denial_reason, sanitize_policyholder_evidence
from claim_agent.workflow.helpers import _kickoff_with_retry

logger = get_logger(__name__)


def run_denial_coverage_workflow(
    denial_data: dict[str, Any],
    *,
    llm: Any | None = None,
    ctx: ClaimContext | None = None,
    state: str = "California",
) -> dict[str, Any]:
    """Run the denial/coverage dispute workflow for a denied claim.

    Args:
        denial_data: Dict with claim_id, denial_reason, and optional policyholder_evidence.
        llm: Optional LLM instance.
        ctx: Dependency-injection context.

    Returns:
        Dict with claim_id, outcome, status, workflow_output, and summary.
    """
    start_time = time.time()

    denial_input = DenialInput.model_validate(denial_data)

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

    claim = repo.get_claim(denial_input.claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {denial_input.claim_id}")

    logger.info(
        "Starting denial/coverage workflow",
        extra={"claim_id": denial_input.claim_id},
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
        "claim_type": claim.get("claim_type"),
        "status": claim.get("status"),
    }

    sanitized_denial_reason = sanitize_denial_reason(denial_input.denial_reason)
    sanitized_evidence = sanitize_policyholder_evidence(denial_input.policyholder_evidence)

    crew_inputs = {
        "claim_data": json.dumps(claim_data_for_crew),
        "denial_data": json.dumps({
            "claim_id": denial_input.claim_id,
            "denial_reason": sanitized_denial_reason,
            "policyholder_evidence": sanitized_evidence,
        }),
    }

    denial_crew = create_denial_coverage_crew(_llm, state=state)
    try:
        result = _kickoff_with_retry(denial_crew, crew_inputs)
    except MidWorkflowEscalation as e:
        # escalate_claim already updated DB (status, review metadata, audit)
        workflow_output = f"Escalated: {e.reason}"
        outcome = "escalated"
        final_status = STATUS_NEEDS_REVIEW
        repo.save_workflow_result(
            denial_input.claim_id,
            "denial_coverage",
            json.dumps(denial_input.model_dump(mode="json")),
            workflow_output,
        )
        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "Denial/coverage workflow escalated",
            extra={
                "claim_id": denial_input.claim_id,
                "outcome": outcome,
                "elapsed_ms": elapsed_ms,
            },
        )
        return {
            "claim_id": denial_input.claim_id,
            "outcome": outcome,
            "status": final_status,
            "workflow_output": workflow_output,
            "summary": f"Escalated for review: {e.reason}",
        }

    workflow_output = _build_workflow_output(result)

    outcome = _parse_outcome(workflow_output)

    if outcome == "route_to_appeal":
        repo.update_claim_status(
            denial_input.claim_id,
            STATUS_NEEDS_REVIEW,
            details=f"Routed to appeal: {workflow_output[:400]}",
        )
        final_status = STATUS_NEEDS_REVIEW
    elif outcome == "escalated":
        repo.update_claim_status(
            denial_input.claim_id,
            STATUS_NEEDS_REVIEW,
            details=f"Escalated for review: {workflow_output[:400]}",
        )
        final_status = STATUS_NEEDS_REVIEW
    else:
        # uphold_denial: status remains denied, letter generated
        final_status = STATUS_DENIED

    repo.save_workflow_result(
        denial_input.claim_id,
        "denial_coverage",
        json.dumps(denial_input.model_dump(mode="json")),
        workflow_output,
    )

    elapsed_ms = (time.time() - start_time) * 1000
    logger.info(
        "Denial/coverage workflow completed",
        extra={
            "claim_id": denial_input.claim_id,
            "outcome": outcome,
            "status": final_status,
            "elapsed_ms": elapsed_ms,
        },
    )

    return {
        "claim_id": denial_input.claim_id,
        "outcome": outcome,
        "status": final_status,
        "workflow_output": workflow_output,
        "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
    }


def _build_workflow_output(result: Any) -> str:
    """Build workflow output from crew result, including denial letter from task 1."""
    tasks_output = getattr(result, "tasks_output", None)
    if tasks_output and isinstance(tasks_output, list) and len(tasks_output) >= 3:
        parts = []
        labels = ["Coverage Analysis", "Denial Letter / Appeal Note", "Final Determination"]
        for i, task in enumerate(tasks_output):
            output = getattr(task, "output", None)
            if output is not None:
                label = labels[i] if i < len(labels) else f"Task {i + 1}"
                parts.append(f"{label}:\n{str(output).strip()}")
        if parts:
            return "\n\n".join(parts)
    return str(
        getattr(result, "raw", None)
        or getattr(result, "output", None)
        or str(result)
    )


def _parse_outcome(workflow_output: str) -> str:
    """Extract outcome from crew output."""
    # First, try to parse structured JSON output and inspect known keys.
    try:
        parsed = json.loads(workflow_output)
    except (TypeError, json.JSONDecodeError, ValueError):
        parsed = None

    if isinstance(parsed, dict):
        def _truthy(value: Any) -> bool:
            if value is True:
                return True
            if isinstance(value, str):
                return value.strip().lower() in {"true", "yes", "1"}
            if isinstance(value, (int, float)):
                return value == 1
            return False

        routed_to_appeal = parsed.get("routed_to_appeal")
        route_to_appeal = parsed.get("route_to_appeal")
        if _truthy(routed_to_appeal) or _truthy(route_to_appeal):
            return "route_to_appeal"

        outcome_field = parsed.get("outcome")
        if isinstance(outcome_field, str):
            outcome_lower = outcome_field.lower()
            if "appeal" in outcome_lower:
                return "route_to_appeal"
            if "escalat" in outcome_lower:
                return "escalated"
            if "uphold" in outcome_lower or "denial" in outcome_lower:
                return "uphold_denial"

    # Fallback: heuristic text search for outcome hints.
    lower = workflow_output.lower()
    if (
        "route_to_appeal" in lower
        or "routed_to_appeal" in lower
        or "routed to appeal" in lower
    ):
        return "route_to_appeal"
    if "escalated" in lower or "escalation" in lower:
        return "escalated"
    if "uphold_denial" in lower or "uphold denial" in lower or "denial upheld" in lower:
        return "uphold_denial"
    return "escalated"
