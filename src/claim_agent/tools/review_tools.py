"""Claim review tools for supervisor/compliance process audit."""

import json

from crewai.tools import tool

from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError


def _get_repo() -> ClaimRepository:
    return ClaimRepository()


@tool("Get Claim Process Context")
def get_claim_process_context(claim_id: str) -> str:
    """Retrieve full process context for claim review: claim record, audit log,
    workflow runs, task checkpoints, and notes. Use for supervisor/compliance review.

    Args:
        claim_id: The claim ID to review.

    Returns:
        JSON with claim, audit_log, workflow_runs, task_checkpoints, and notes.
    """
    repo = _get_repo()
    claim = repo.get_claim(claim_id)
    if claim is None:
        raise ClaimNotFoundError(f"Claim not found: {claim_id}")

    audit_entries, _ = repo.get_claim_history(claim_id)
    audit_log = [
        {
            "action": e.get("action"),
            "old_status": e.get("old_status"),
            "new_status": e.get("new_status"),
            "details": (e.get("details") or "")[:500],
            "actor_id": e.get("actor_id"),
            "created_at": e.get("created_at"),
        }
        for e in audit_entries
    ]

    workflow_runs = repo.get_workflow_runs(claim_id, limit=5)
    runs_out = [
        {
            "claim_type": r.get("claim_type"),
            "router_output": (r.get("router_output") or "")[:2000],
            "workflow_output": (r.get("workflow_output") or "")[:4000],
            "created_at": r.get("created_at"),
        }
        for r in workflow_runs
    ]

    task_checkpoints: list[dict] = []
    latest_run_id = repo.get_latest_checkpointed_run_id(claim_id)
    if latest_run_id:
        checkpoints = repo.get_task_checkpoints(claim_id, latest_run_id)
        for stage_key, output in checkpoints.items():
            task_checkpoints.append({
                "stage_key": stage_key,
                "output": (output or "")[:2000] if output else "",
            })

    notes = repo.get_notes(claim_id)
    notes_out = [
        {
            "note": n.get("note", "")[:1000],
            "actor_id": n.get("actor_id"),
            "created_at": n.get("created_at"),
        }
        for n in notes
    ]

    result = {
        "claim": {
            "id": claim.get("id"),
            "status": claim.get("status"),
            "claim_type": claim.get("claim_type"),
            "policy_number": claim.get("policy_number"),
            "vin": claim.get("vin"),
            "incident_date": claim.get("incident_date"),
            "payout_amount": claim.get("payout_amount"),
            "created_at": claim.get("created_at"),
            "updated_at": claim.get("updated_at"),
        },
        "audit_log": audit_log,
        "workflow_runs": runs_out,
        "task_checkpoints": task_checkpoints,
        "notes": notes_out,
    }
    return json.dumps(result, default=str)
