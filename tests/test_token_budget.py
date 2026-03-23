"""Tests for token budget enforcement in main crew."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.crews.main_crew import (
    TokenBudgetExceeded,
    _check_token_budget,
)
from claim_agent.observability.metrics import ClaimMetrics, calculate_cost
from claim_agent.workflow.budget import BudgetEnforcingCallback


def test_calculate_cost_returns_zero_for_invalid_inputs():
    """calculate_cost returns 0.0 when given mock objects or invalid types."""
    assert calculate_cost(MagicMock(), 100, 50) == 0.0
    assert calculate_cost(123, 100, 50) == 0.0
    assert calculate_cost("gpt-4o-mini", MagicMock(), 50) == 0.0
    assert calculate_cost("gpt-4o-mini", 100, MagicMock()) == 0.0


def test_check_token_budget_passes_when_under_limit():
    """_check_token_budget does not raise when under limit."""
    metrics = ClaimMetrics()
    metrics.start_claim("CLM-TEST")
    metrics.record_llm_call(
        claim_id="CLM-TEST",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=50,
        cost_usd=0.001,
        latency_ms=100,
        status="success",
    )
    metrics.end_claim("CLM-TEST", status="open")
    _check_token_budget("CLM-TEST", metrics)


def test_check_token_budget_raises_when_tokens_exceeded():
    """_check_token_budget raises TokenBudgetExceeded when token limit exceeded."""
    metrics = ClaimMetrics()
    metrics.start_claim("CLM-TEST")
    metrics.record_llm_call(
        claim_id="CLM-TEST",
        model="gpt-4o-mini",
        input_tokens=60,
        output_tokens=60,
        cost_usd=0.001,
        latency_ms=100,
        status="success",
    )
    metrics.end_claim("CLM-TEST", status="open")

    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 100):
        with pytest.raises(TokenBudgetExceeded) as exc_info:
            _check_token_budget("CLM-TEST", metrics)
    assert "Token budget exceeded" in str(exc_info.value)


def test_check_token_budget_uses_llm_fallback_when_metrics_empty():
    """_check_token_budget falls back to llm.get_token_usage_summary when metrics have no records."""
    metrics = ClaimMetrics()
    metrics.start_claim("CLM-FALLBACK")
    # No record_llm_call - metrics have 0 tokens, 0 calls

    usage = SimpleNamespace(
        prompt_tokens=50,
        completion_tokens=25,
        successful_requests=1,
    )
    stub_llm = SimpleNamespace(
        model="gpt-4o-mini",
        get_token_usage_summary=lambda: usage,
    )

    # Under limit: should not raise
    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 100):
        _check_token_budget("CLM-FALLBACK", metrics, llm=stub_llm)

    # Over limit: should raise
    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 50):
        with pytest.raises(TokenBudgetExceeded) as exc_info:
            _check_token_budget("CLM-FALLBACK", metrics, llm=stub_llm)
    assert "Token budget exceeded" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Tests for BudgetEnforcingCallback (intra-crew budget checks)
# ---------------------------------------------------------------------------


def _make_metrics_with_tokens(claim_id: str, input_tokens: int, output_tokens: int) -> ClaimMetrics:
    """Helper: create ClaimMetrics pre-seeded with one LLM call."""
    metrics = ClaimMetrics()
    metrics.start_claim(claim_id)
    metrics.record_llm_call(
        claim_id=claim_id,
        model="gpt-4o-mini",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=0.001,
        latency_ms=100,
        status="success",
    )
    return metrics


def test_budget_enforcing_callback_no_exception_when_under_limit():
    """BudgetEnforcingCallback stores no exception when usage is within budget."""
    metrics = _make_metrics_with_tokens("CLM-CB1", 50, 50)
    cb = BudgetEnforcingCallback("CLM-CB1", metrics)

    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 200):
        cb.log_success_event({}, None, 0.0, 0.1)

    assert cb.stored_exception is None
    # raise_if_exceeded should not raise
    cb.raise_if_exceeded()


def test_budget_enforcing_callback_stores_exception_when_exceeded():
    """BudgetEnforcingCallback stores TokenBudgetExceeded when usage exceeds limit."""
    metrics = _make_metrics_with_tokens("CLM-CB2", 60, 60)
    cb = BudgetEnforcingCallback("CLM-CB2", metrics)

    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 100):
        cb.log_success_event({}, None, 0.0, 0.1)

    assert cb.stored_exception is not None
    assert isinstance(cb.stored_exception, TokenBudgetExceeded)
    assert "Token budget exceeded" in str(cb.stored_exception)


def test_budget_enforcing_callback_raise_if_exceeded_propagates():
    """raise_if_exceeded re-raises stored TokenBudgetExceeded."""
    metrics = _make_metrics_with_tokens("CLM-CB3", 80, 80)
    cb = BudgetEnforcingCallback("CLM-CB3", metrics)

    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 100):
        cb.log_success_event({}, None, 0.0, 0.1)

    with pytest.raises(TokenBudgetExceeded):
        cb.raise_if_exceeded()


def test_budget_enforcing_callback_idempotent_on_multiple_calls():
    """BudgetEnforcingCallback stores the exception only once even when called multiple times."""
    metrics = _make_metrics_with_tokens("CLM-CB4", 60, 60)
    cb = BudgetEnforcingCallback("CLM-CB4", metrics)

    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 100):
        cb.log_success_event({}, None, 0.0, 0.1)
        first_exc = cb.stored_exception
        cb.log_success_event({}, None, 0.0, 0.1)

    # stored_exception should still be the same object (not overwritten)
    assert cb.stored_exception is first_exc


def test_kickoff_with_retry_raises_budget_exceeded_and_does_not_retry():
    """_kickoff_with_retry re-raises TokenBudgetExceeded from budget_callback without retrying."""
    from claim_agent.workflow.helpers import _kickoff_with_retry

    metrics = _make_metrics_with_tokens("CLM-KR1", 60, 60)
    cb = BudgetEnforcingCallback("CLM-KR1", metrics)

    # Patch the budget limit so the callback will detect an exceeded budget.
    # The mock crew kickoff succeeds; BudgetEnforcingCallback stores the exception;
    # _kickoff_with_retry detects it via raise_if_exceeded.
    call_count = 0

    class _MockCrew:
        def kickoff(self, inputs):
            nonlocal call_count
            call_count += 1
            # Simulate a LLM call that updates metrics beyond limit during kickoff
            metrics.record_llm_call(
                claim_id="CLM-KR1",
                model="gpt-4o-mini",
                input_tokens=1,
                output_tokens=1,
                cost_usd=0.0,
                latency_ms=1,
                status="success",
            )
            # Manually trigger the callback as litellm would during a real run
            with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 100):
                cb.log_success_event({}, None, 0.0, 0.1)
            return SimpleNamespace(raw="done")

    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 100):
        with pytest.raises(TokenBudgetExceeded):
            _kickoff_with_retry(_MockCrew(), {}, budget_callback=cb)

    # Should have been called exactly once - not retried
    assert call_count == 1


def test_kickoff_with_retry_budget_callback_installed_and_removed():
    """_kickoff_with_retry installs budget_callback on litellm.callbacks and removes it after."""
    import litellm

    from claim_agent.workflow.helpers import _kickoff_with_retry

    metrics = ClaimMetrics()
    metrics.start_claim("CLM-KR2")
    cb = BudgetEnforcingCallback("CLM-KR2", metrics)

    original_callbacks = list(getattr(litellm, "callbacks", None) or [])

    class _MockCrew:
        def kickoff(self, inputs):
            return SimpleNamespace(raw="ok")

    _kickoff_with_retry(_MockCrew(), {}, budget_callback=cb)

    # After kickoff, the budget callback should be removed
    current_callbacks = list(getattr(litellm, "callbacks", None) or [])
    assert cb not in current_callbacks
    assert current_callbacks == original_callbacks

