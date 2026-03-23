"""Small stateless helpers shared across workflow modules."""

import threading
import types
from typing import TYPE_CHECKING, Any, Callable, Optional

import litellm

from claim_agent.config.llm import _set_model_override, get_llm_fallback_chain
from claim_agent.db.constants import (
    STATUS_CLOSED,
    STATUS_DUPLICATE,
    STATUS_FRAUD_SUSPECTED,
    STATUS_OPEN,
    STATUS_SETTLED,
)
from claim_agent.exceptions import TokenBudgetExceeded
from claim_agent.models.claim import ClaimType
from claim_agent.observability import get_logger
from claim_agent.utils.retry import with_llm_retry

logger = get_logger(__name__)
if TYPE_CHECKING:
    from claim_agent.workflow.budget import BudgetEnforcingCallback

# Use the same global callbacks lock as workflow.orchestrator to protect
# litellm.callbacks modifications during kickoff budget-callback install/uninstall.


class _CallbacksLockProxy:
    """Context-manager proxy that delegates to orchestrator's shared callbacks lock.

    The lock reference is resolved lazily on first use to avoid a circular import
    (orchestrator imports helpers at module level).  It is cached as a class attribute
    so all proxy instances share the single ``orchestrator._callbacks_lock`` object;
    this prevents the per-instance ``self._lock`` assignment race that would occur if
    two threads entered the same proxy instance concurrently.
    """

    _lock: Optional[threading.Lock] = None

    @classmethod
    def _get_lock(cls) -> threading.Lock:
        if cls._lock is None:
            # Local import to avoid circular dependencies at module import time.
            from claim_agent.workflow import orchestrator  # type: ignore[import]

            cls._lock = orchestrator._callbacks_lock  # type: ignore[attr-defined]
        return cls._lock

    def __enter__(self) -> threading.Lock:
        lock = self._get_lock()
        lock.acquire()
        return lock

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: types.TracebackType | None,
    ) -> None:
        # Always release; standard Lock semantics handle re-entrancy errors.
        self._get_lock().release()


_budget_callbacks_lock = _CallbacksLockProxy()


WORKFLOW_STAGES = (
    "coverage_verification",
    "economic_analysis", "fraud_prescreening", "duplicate_detection",
    "router", "escalation_check", "workflow",
    "task_creation",
    "rental",
    "liability_determination",
    "settlement", "subrogation", "salvage",
    "after_action",
)


def _final_status(claim_type: str) -> str:
    """Map claim_type to final claim status."""
    if claim_type == ClaimType.NEW.value:
        return STATUS_OPEN
    if claim_type == ClaimType.DUPLICATE.value:
        return STATUS_DUPLICATE
    if claim_type == ClaimType.FRAUD.value:
        return STATUS_FRAUD_SUSPECTED
    if claim_type in (
        ClaimType.PARTIAL_LOSS.value,
        ClaimType.TOTAL_LOSS.value,
        ClaimType.BODILY_INJURY.value,
    ):
        return STATUS_SETTLED
    return STATUS_CLOSED


def _requires_settlement(claim_type: str) -> bool:
    """Return True when the workflow should hand off to the shared settlement crew."""
    return claim_type in (
        ClaimType.PARTIAL_LOSS.value,
        ClaimType.TOTAL_LOSS.value,
        ClaimType.BODILY_INJURY.value,
    )


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
    if claim_type not in (
        ClaimType.PARTIAL_LOSS.value,
        ClaimType.TOTAL_LOSS.value,
        ClaimType.BODILY_INJURY.value,
    ):
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


def _kickoff_with_retry(
    crew: Any,
    inputs: dict[str, Any],
    create_crew_no_args: Callable[[], Any] | None = None,
    claim_id: str | None = None,
    metrics: Any | None = None,
    llm: Any | None = None,
    *,
    budget_callback: "BudgetEnforcingCallback | None" = None,
) -> Any:
    """Run crew.kickoff with retry on transient failures.

    When create_crew_no_args is provided, on failure the retry loop tries each
    fallback model from OPENAI_FALLBACK_MODELS by setting a thread-local model
    override before recreating the crew via the factory.  Callers that don't
    need model fallback can omit the factory entirely.

    Budget-driven fallback (LLM_BUDGET_FALLBACK_ENABLED):
        When enabled and *claim_id* + *metrics* are provided, the function checks
        whether the claim has already consumed ≥ LLM_BUDGET_FALLBACK_THRESHOLD of
        MAX_TOKENS_PER_CLAIM or MAX_LLM_CALLS_PER_CLAIM before the first attempt.
        If the threshold is breached and a cheaper fallback model exists in the
        chain, the crew is recreated with that model instead of waiting for a hard
        TokenBudgetExceeded exception.  This works the same as the exception-driven
        path but is triggered by budget proximity rather than a runtime error.

        Thread-local note: model override is scoped to the current thread only and
        does not propagate to worker processes or async tasks in other threads.
    When budget_callback is provided it is installed on ``litellm.callbacks`` for
    the duration of the kickoff so that ``_check_token_budget`` fires after every
    successful intra-crew LLM call.  ``TokenBudgetExceeded`` is never retried
    with a fallback model; it propagates immediately.
    """
    models = get_llm_fallback_chain()
    last_exc: BaseException | None = None
    use_fallback = create_crew_no_args is not None and len(models) > 1
    installed_budget_callback = False

    start_index = 0
    if use_fallback and claim_id is not None and metrics is not None:
        from claim_agent.config.settings import get_settings
        from claim_agent.workflow.budget import _is_budget_approaching

        llm_cfg = get_settings().llm
        if llm_cfg.budget_fallback_enabled and _is_budget_approaching(
            claim_id, metrics, llm=llm, threshold=llm_cfg.budget_fallback_threshold
        ):
            start_index = 1
            logger.info(
                "budget_driven_fallback claim_id=%s from_model=%s to_model=%s threshold=%.2f",
                claim_id,
                models[0],
                models[start_index],
                llm_cfg.budget_fallback_threshold,
            )

    if use_fallback:
        indices_and_names = list(enumerate(models[start_index:], start=start_index))
    else:
        indices_and_names = [(0, models[0])] if models else []

    try:
        if budget_callback is not None:
            with _budget_callbacks_lock:
                prev_cbs = list(getattr(litellm, "callbacks", None) or [])
                litellm.callbacks = prev_cbs + [budget_callback]
            installed_budget_callback = True

        for global_idx, model_name in indices_and_names:
            if use_fallback and global_idx > 0:
                _set_model_override(model_name)
                try:
                    assert create_crew_no_args is not None
                    current_crew = create_crew_no_args()
                finally:
                    _set_model_override(None)
            else:
                current_crew = crew

            @with_llm_retry()
            def _call(c: Any = current_crew) -> Any:
                return c.kickoff(inputs=inputs)

            try:
                result = _call()
                if budget_callback is not None:
                    budget_callback.raise_if_exceeded()
                return result
            except TokenBudgetExceeded:
                raise  # never retry on budget exceeded
            except Exception as e:
                last_exc = e
                if not use_fallback or model_name == models[-1]:
                    raise
                continue

        if last_exc:
            raise last_exc
        raise RuntimeError("kickoff failed with no exception")
    finally:
        if installed_budget_callback and budget_callback is not None:
            with _budget_callbacks_lock:
                curr_cbs = list(getattr(litellm, "callbacks", None) or [])
                litellm.callbacks = [cb for cb in curr_cbs if cb is not budget_callback]


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
