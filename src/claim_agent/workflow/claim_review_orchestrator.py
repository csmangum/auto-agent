"""Claim review orchestrator: runs supervisor/compliance audit of the claim process."""

import json

from claim_agent.context import ClaimContext
from claim_agent.crews.claim_review_crew import create_claim_review_crew
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.claim_review import ClaimReviewReport
from claim_agent.tools.review_tools import set_claim_review_db_path
from claim_agent.workflow.helpers import _kickoff_with_retry


def run_claim_review(
    claim_id: str,
    *,
    actor_id: str | None = None,
    ctx: ClaimContext | None = None,
) -> ClaimReviewReport:
    """Run supervisor/compliance review on the claim process.

    Args:
        claim_id: The claim ID to review.
        actor_id: Actor performing the review (for audit trail).
        ctx: ClaimContext. When None, built from defaults.

    Returns:
        ClaimReviewReport with issues, compliance_checks, and recommendations.

    Raises:
        ClaimNotFoundError: If the claim does not exist.
    """
    if ctx is None:
        ctx = ClaimContext.from_defaults()

    claim = ctx.repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    workflow_runs = ctx.repo.get_workflow_runs(claim_id, limit=1)
    workflow_output = ""
    if workflow_runs:
        workflow_output = workflow_runs[0].get("workflow_output") or ""

    claim_data = json.dumps({
        "id": claim.get("id"),
        "status": claim.get("status"),
        "claim_type": claim.get("claim_type"),
        "policy_number": claim.get("policy_number"),
        "vin": claim.get("vin"),
        "incident_date": claim.get("incident_date"),
        "incident_description": claim.get("incident_description"),
        "damage_description": claim.get("damage_description"),
        "payout_amount": claim.get("payout_amount"),
        "created_at": claim.get("created_at"),
        "updated_at": claim.get("updated_at"),
    }, default=str)

    # Ensure review tools use the same db as this context (for multi-DB/simulation)
    db_path = getattr(ctx.repo, "_db_path", None)
    set_claim_review_db_path(db_path)

    crew = create_claim_review_crew(ctx.llm)
    result = _kickoff_with_retry(crew, {
        "claim_id": claim_id,
        "claim_data": claim_data,
        "workflow_output": workflow_output,
    })

    raw = str(
        getattr(result, "raw", None)
        or getattr(result, "output", None)
        or str(result)
    )

    tasks_output = getattr(result, "tasks_output", None)
    if tasks_output and isinstance(tasks_output, list) and len(tasks_output) > 0:
        last_task = tasks_output[-1]
        pydantic_out = getattr(last_task, "pydantic", None) or getattr(last_task, "output", None)
        if isinstance(pydantic_out, ClaimReviewReport):
            return pydantic_out

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "claim_id" in parsed:
            return ClaimReviewReport.model_validate(parsed)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    return ClaimReviewReport(
        claim_id=claim_id,
        overall_pass=False,
        issues=[],
        compliance_checks=[],
        recommendations=["Review output could not be parsed; manual review recommended."],
    )
