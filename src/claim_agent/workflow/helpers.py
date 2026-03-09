"""Small stateless helpers shared across workflow modules."""

from typing import Any

from claim_agent.db.constants import (
    STATUS_CLOSED,
    STATUS_DUPLICATE,
    STATUS_FRAUD_SUSPECTED,
    STATUS_OPEN,
    STATUS_SETTLED,
)
from claim_agent.models.claim import ClaimType
from claim_agent.utils.retry import with_llm_retry


WORKFLOW_STAGES = ("router", "escalation_check", "workflow", "rental", "settlement", "subrogation", "salvage")


def _final_status(claim_type: str) -> str:
    """Map claim_type to final claim status."""
    if claim_type == ClaimType.NEW.value:
        return STATUS_OPEN
    if claim_type == ClaimType.DUPLICATE.value:
        return STATUS_DUPLICATE
    if claim_type == ClaimType.FRAUD.value:
        return STATUS_FRAUD_SUSPECTED
    if claim_type in (ClaimType.PARTIAL_LOSS.value, ClaimType.TOTAL_LOSS.value):
        return STATUS_SETTLED
    return STATUS_CLOSED


def _requires_settlement(claim_type: str) -> bool:
    """Return True when the workflow should hand off to the shared settlement crew."""
    return claim_type in (ClaimType.PARTIAL_LOSS.value, ClaimType.TOTAL_LOSS.value)


def _requires_salvage(claim_type: str) -> bool:
    """Return True when the workflow should run the salvage crew (total_loss only)."""
    return claim_type == ClaimType.TOTAL_LOSS.value


def _combine_workflow_outputs(
    primary_output: str,
    settlement_output: str | None = None,
    label: str = "Settlement workflow output",
) -> str:
    """Combine primary workflow and settlement outputs for persistence and summaries."""
    if not settlement_output:
        return primary_output

    if "Primary workflow output:\n" in primary_output:
        return f"{primary_output}\n\n{label}:\n{settlement_output}"

    return f"Primary workflow output:\n{primary_output}\n\n{label}:\n{settlement_output}"


def _extract_payout_from_workflow_result(result: Any, claim_type: str) -> float | None:
    """Extract payout_amount from workflow crew result when output_pydantic was used.

    For total_loss and partial_loss, the final task uses output_pydantic. The last
    task's output may be a Pydantic model with payout_amount. Returns None if
    extraction fails (Settlement Crew will infer from workflow_output text).
    """
    if claim_type not in (ClaimType.PARTIAL_LOSS.value, ClaimType.TOTAL_LOSS.value):
        return None
    tasks_output = getattr(result, "tasks_output", None)
    if not tasks_output or not isinstance(tasks_output, list):
        return None
    try:
        last_task = tasks_output[-1]
        output = getattr(last_task, "output", None)
        if output is None:
            return None
        val = None
        if hasattr(output, "payout_amount"):
            val = getattr(output, "payout_amount")
        elif isinstance(output, dict) and "payout_amount" in output:
            val = output["payout_amount"]
        if val is not None and isinstance(val, (int, float)) and val >= 0:
            return float(val)
    except (IndexError, TypeError, AttributeError, KeyError):
        pass
    return None


def _kickoff_with_retry(crew: Any, inputs: dict[str, Any]) -> Any:
    """Run crew.kickoff with retry on transient failures."""

    @with_llm_retry()
    def _call() -> Any:
        return crew.kickoff(inputs=inputs)

    return _call()


def _checkpoint_keys_to_invalidate(from_stage: str, checkpoints: dict[str, str]) -> list[str]:
    """Return checkpoint keys to delete when resuming from *from_stage* onwards."""
    try:
        idx = WORKFLOW_STAGES.index(from_stage)
    except ValueError:
        return []
    stages_to_drop = set(WORKFLOW_STAGES[idx:])
    return [
        key for key in checkpoints if (key.split(":")[0] if ":" in key else key) in stages_to_drop
    ]
