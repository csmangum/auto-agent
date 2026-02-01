"""Tests for token budget enforcement in main crew."""

from unittest.mock import patch

import pytest

from claim_agent.crews.main_crew import TokenBudgetExceeded, _check_token_budget
from claim_agent.observability.metrics import ClaimMetrics


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

    with patch("claim_agent.crews.main_crew.MAX_TOKENS_PER_CLAIM", 100):
        with pytest.raises(TokenBudgetExceeded) as exc_info:
            _check_token_budget("CLM-TEST", metrics)
    assert "Token budget exceeded" in str(exc_info.value)
