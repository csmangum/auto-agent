"""Token and LLM-call budget enforcement."""

from typing import Any

from claim_agent.config.llm import get_model_name
from claim_agent.config.settings import MAX_LLM_CALLS_PER_CLAIM, MAX_TOKENS_PER_CLAIM
from claim_agent.exceptions import TokenBudgetExceeded
from claim_agent.observability import get_logger

logger = get_logger(__name__)


def _get_llm_usage_snapshot(llm: Any) -> tuple[int, int, int] | None:
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


def _check_token_budget(claim_id: str, metrics: Any, llm: Any | None = None) -> None:
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


def _record_crew_llm_usage(claim_id: str, llm: Any, metrics: Any) -> None:
    """Record CrewAI LLM token usage and cost into metrics for this claim.

    CrewAI uses native SDK (OpenAI etc.) for standard models, so LiteLLM callbacks
    are not invoked. The LLM instance accumulates usage via get_token_usage_summary().
    We record one aggregated call so evaluation and reporting get real token/cost data.
    """
    usage = _get_llm_usage_snapshot(llm)
    if usage is None:
        return
    prompt_tokens, completion_tokens, _successful_requests = usage
    model = getattr(llm, "model", None) or get_model_name()
    if not isinstance(model, str):
        model = get_model_name()
    metrics.record_llm_call(
        claim_id=claim_id,
        model=model,
        input_tokens=prompt_tokens,
        output_tokens=completion_tokens,
        cost_usd=None,
        latency_ms=0.0,
        status="success",
    )
