"""Token and LLM-call budget enforcement."""

import threading
from typing import Any

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.config.llm import get_model_name
from claim_agent.config.settings import MAX_LLM_CALLS_PER_CLAIM, MAX_TOKENS_PER_CLAIM
from claim_agent.exceptions import TokenBudgetExceeded
from claim_agent.observability import get_logger

logger = get_logger(__name__)


def _get_litellm_custom_logger_base() -> type:
    """Return CustomLogger base class for LiteLLM callback; optional to avoid hard dependency."""
    try:
        from litellm.integrations.custom_logger import CustomLogger

        return CustomLogger  # type: ignore[return-value]
    except ImportError:
        return object


class BudgetEnforcingCallback(_get_litellm_custom_logger_base()):  # type: ignore[misc]
    """LiteLLM callback that enforces the token/call budget after each LLM call within a crew.

    Install this callback on ``litellm.callbacks`` for the duration of a crew ``kickoff``.
    After each successful LLM call the callback calls ``_check_token_budget``; when the budget
    is exceeded it stores the resulting ``TokenBudgetExceeded`` on ``stored_exception`` so that
    the kickoff wrapper can re-raise it after the call returns.

    LiteLLM swallows exceptions raised inside callbacks, so the two-step approach
    (store + re-raise by the caller) is necessary to propagate the budget error.
    """

    def __init__(self, claim_id: str, metrics: Any) -> None:
        base = _get_litellm_custom_logger_base()
        if base is not object:
            super().__init__()
        self.claim_id = claim_id
        self.metrics = metrics
        self.stored_exception: TokenBudgetExceeded | None = None
        self._lock = threading.Lock()

    def log_success_event(
        self,
        kwargs: dict[str, Any],
        response_obj: Any,
        start_time: float,
        end_time: float,
    ) -> None:
        """Called after each successful LLM API call; check budget and store any violation."""
        try:
            _check_token_budget(self.claim_id, self.metrics)
        except TokenBudgetExceeded as exc:
            with self._lock:
                if self.stored_exception is None:
                    self.stored_exception = exc
                    do_log = True
                else:
                    do_log = False
            if do_log:
                logger.warning(
                    "Intra-crew budget exceeded for claim %s: %s",
                    self.claim_id,
                    exc,
                    extra={"claim_id": self.claim_id},
                )

    def raise_if_exceeded(self) -> None:
        """Re-raise a stored ``TokenBudgetExceeded`` (call this after kickoff returns)."""
        with self._lock:
            exc = self.stored_exception
        if exc is not None:
            raise exc


def _get_llm_usage_snapshot(llm: LLMProtocol) -> tuple[int, int, int] | None:
    """Best-effort token usage snapshot from CrewAI LLM."""
    get_usage = getattr(llm, "get_token_usage_summary", None)
    if get_usage is None:
        return None
    try:
        usage = get_usage()
    except Exception as exc:
        logger.debug(
            "Failed to get LLM token usage summary: %s",
            exc,
            exc_info=True,
        )
        return None
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    successful_requests = getattr(usage, "successful_requests", 0) or 0
    if not isinstance(prompt_tokens, (int, float)) or not isinstance(completion_tokens, (int, float)):
        return None
    if not isinstance(successful_requests, (int, float)):
        successful_requests = 0
    if (prompt_tokens + completion_tokens) == 0 and successful_requests == 0:
        return None
    return int(prompt_tokens), int(completion_tokens), int(successful_requests or 0)


def _check_token_budget(claim_id: str, metrics: Any, llm: LLMProtocol | None = None) -> None:
    """Raise TokenBudgetExceeded if claim exceeds configured token or call budget."""
    summary = metrics.get_claim_summary(claim_id)
    total_tokens = summary.total_tokens if summary is not None else 0
    total_calls = summary.total_llm_calls if summary is not None else 0

    if total_tokens == 0 and total_calls == 0 and llm is not None:
        usage = _get_llm_usage_snapshot(llm)
        if usage is not None:
            prompt_tokens, completion_tokens, successful_requests = usage
            total_tokens = prompt_tokens + completion_tokens
            total_calls = successful_requests or (1 if total_tokens > 0 else 0)

    if total_tokens > MAX_TOKENS_PER_CLAIM:
        raise TokenBudgetExceeded(
            claim_id,
            total_tokens,
            total_calls,
            f"Token budget exceeded: {total_tokens} > {MAX_TOKENS_PER_CLAIM}",
        )
    if total_calls > MAX_LLM_CALLS_PER_CLAIM:
        raise TokenBudgetExceeded(
            claim_id,
            total_tokens,
            total_calls,
            f"LLM call budget exceeded: {total_calls} > {MAX_LLM_CALLS_PER_CLAIM}",
        )


def _record_crew_usage_delta(
    claim_id: str,
    llm: LLMProtocol | None,
    metrics: Any,
    crew: str,
    claim_type: str | None = None,
) -> None:
    """Record token delta for a crew (per-crew cost attribution). Call after each crew kickoff."""
    if llm is None:
        return
    usage = _get_llm_usage_snapshot(llm)
    if usage is None:
        return
    prompt_tokens, completion_tokens, _ = usage
    model = llm.model if isinstance(llm.model, str) else get_model_name()
    metrics.record_crew_usage_delta(
        claim_id=claim_id,
        current_prompt=prompt_tokens,
        current_completion=completion_tokens,
        model=model,
        crew=crew,
        claim_type=claim_type,
    )
