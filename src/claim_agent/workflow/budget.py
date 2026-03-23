"""Token and LLM-call budget enforcement."""

from typing import Any

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.config.llm import get_model_name
from claim_agent.config.settings import MAX_LLM_CALLS_PER_CLAIM, MAX_TOKENS_PER_CLAIM
from claim_agent.exceptions import TokenBudgetExceeded
from claim_agent.observability import get_logger

logger = get_logger(__name__)


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


def _is_budget_approaching(
    claim_id: str,
    metrics: Any,
    llm: LLMProtocol | None = None,
    threshold: float | None = None,
) -> bool:
    """Return True when the claim is approaching the configured token or call budget.

    Uses the same usage-snapshot logic as ``_check_token_budget``.  When *threshold*
    is ``None`` the value is read from ``LLMConfig.budget_fallback_threshold``
    (env: ``LLM_BUDGET_FALLBACK_THRESHOLD``, default 0.9).

    This function is intentionally non-raising: callers use the return value to
    decide whether to proactively switch to a cheaper fallback model before the
    hard ``TokenBudgetExceeded`` exception fires.
    """
    from claim_agent.config.settings import get_settings  # avoid circular import at module level

    if threshold is None:
        threshold = get_settings().llm.budget_fallback_threshold

    summary = metrics.get_claim_summary(claim_id)
    total_tokens = summary.total_tokens if summary is not None else 0
    total_calls = summary.total_llm_calls if summary is not None else 0

    if total_tokens == 0 and total_calls == 0 and llm is not None:
        usage = _get_llm_usage_snapshot(llm)
        if usage is not None:
            prompt_tokens, completion_tokens, successful_requests = usage
            total_tokens = prompt_tokens + completion_tokens
            total_calls = successful_requests or (1 if total_tokens > 0 else 0)

    token_ratio = total_tokens / MAX_TOKENS_PER_CLAIM if MAX_TOKENS_PER_CLAIM > 0 else 0.0
    call_ratio = total_calls / MAX_LLM_CALLS_PER_CLAIM if MAX_LLM_CALLS_PER_CLAIM > 0 else 0.0
    return token_ratio >= threshold or call_ratio >= threshold


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
