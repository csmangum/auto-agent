"""Tests for token budget enforcement in main crew."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.crews.main_crew import (
    TokenBudgetExceeded,
    _check_token_budget,
)
from claim_agent.observability.metrics import ClaimMetrics, calculate_cost


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


