"""Tests for token budget enforcement in main crew."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.crews.main_crew import (
    TokenBudgetExceeded,
    _check_token_budget,
)
from claim_agent.observability.metrics import ClaimMetrics, calculate_cost
from claim_agent.workflow.budget import _is_budget_approaching
from claim_agent.workflow.helpers import _kickoff_with_retry


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


def test_is_budget_approaching_returns_false_under_threshold():
    """_is_budget_approaching returns False when usage is well below threshold."""
    metrics = ClaimMetrics()
    metrics.start_claim("CLM-APPROACH-UNDER")
    metrics.record_llm_call(
        claim_id="CLM-APPROACH-UNDER",
        model="gpt-4o-mini",
        input_tokens=100,
        output_tokens=100,
        cost_usd=0.001,
        latency_ms=100,
        status="success",
    )
    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 10_000):
        with patch("claim_agent.workflow.budget.MAX_LLM_CALLS_PER_CLAIM", 50):
            assert not _is_budget_approaching("CLM-APPROACH-UNDER", metrics, threshold=0.9)


def test_is_budget_approaching_returns_true_at_threshold():
    """_is_budget_approaching returns True when token usage reaches threshold."""
    metrics = ClaimMetrics()
    metrics.start_claim("CLM-APPROACH-HIT")
    metrics.record_llm_call(
        claim_id="CLM-APPROACH-HIT",
        model="gpt-4o-mini",
        input_tokens=4600,
        output_tokens=500,
        cost_usd=0.001,
        latency_ms=100,
        status="success",
    )
    # 5100 tokens out of 5000 cap → ratio > 1.0 ≥ 0.9
    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 5_000):
        with patch("claim_agent.workflow.budget.MAX_LLM_CALLS_PER_CLAIM", 50):
            assert _is_budget_approaching("CLM-APPROACH-HIT", metrics, threshold=0.9)


def test_is_budget_approaching_returns_true_on_call_ratio():
    """_is_budget_approaching triggers on call count even when tokens are low."""
    metrics = ClaimMetrics()
    metrics.start_claim("CLM-CALLS-HIT")
    for _ in range(9):
        metrics.record_llm_call(
            claim_id="CLM-CALLS-HIT",
            model="gpt-4o-mini",
            input_tokens=10,
            output_tokens=10,
            cost_usd=0.0001,
            latency_ms=50,
            status="success",
        )
    # 9 calls out of 10 cap → 90% ≥ 0.9 threshold
    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 150_000):
        with patch("claim_agent.workflow.budget.MAX_LLM_CALLS_PER_CLAIM", 10):
            assert _is_budget_approaching("CLM-CALLS-HIT", metrics, threshold=0.9)


def test_is_budget_approaching_uses_llm_snapshot_when_metrics_empty():
    """_is_budget_approaching falls back to LLM snapshot when metrics have no data."""
    metrics = ClaimMetrics()
    metrics.start_claim("CLM-SNAP")
    # No record_llm_call – metrics have 0 tokens/calls

    stub_usage = SimpleNamespace(prompt_tokens=4600, completion_tokens=500, successful_requests=1)
    stub_llm = SimpleNamespace(model="gpt-4o-mini", get_token_usage_summary=lambda: stub_usage)

    with patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 5_000):
        with patch("claim_agent.workflow.budget.MAX_LLM_CALLS_PER_CLAIM", 50):
            assert _is_budget_approaching("CLM-SNAP", metrics, llm=stub_llm, threshold=0.9)


def test_kickoff_with_retry_budget_fallback_switches_to_fallback_model():
    """_kickoff_with_retry uses fallback crew when budget threshold is approaching."""
    primary_crew = MagicMock()
    primary_crew.kickoff.return_value = "primary-result"
    fallback_crew = MagicMock()
    fallback_crew.kickoff.return_value = "fallback-result"

    fallback_crews = []

    def make_crew():
        fallback_crews.append(fallback_crew)
        return fallback_crew

    metrics = ClaimMetrics()
    metrics.start_claim("CLM-BDF")
    metrics.record_llm_call(
        claim_id="CLM-BDF",
        model="gpt-4o-mini",
        input_tokens=4600,
        output_tokens=500,
        cost_usd=0.001,
        latency_ms=100,
        status="success",
    )

    mock_llm_cfg = MagicMock()
    mock_llm_cfg.budget_fallback_enabled = True
    mock_llm_cfg.budget_fallback_threshold = 0.9
    mock_settings = MagicMock()
    mock_settings.llm = mock_llm_cfg

    with (
        patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 5_000),
        patch("claim_agent.workflow.budget.MAX_LLM_CALLS_PER_CLAIM", 50),
        patch("claim_agent.workflow.helpers.get_llm_fallback_chain", return_value=["gpt-4o-mini", "gpt-3.5-turbo"]),
        patch("claim_agent.workflow.helpers._set_model_override"),
        patch("claim_agent.config.settings.get_settings", return_value=mock_settings),
    ):
        result = _kickoff_with_retry(
            primary_crew,
            {},
            create_crew_no_args=make_crew,
            claim_id="CLM-BDF",
            metrics=metrics,
        )

    # The fallback crew should be used (not the primary)
    assert result == "fallback-result"
    primary_crew.kickoff.assert_not_called()
    assert len(fallback_crews) == 1


def test_kickoff_with_retry_budget_fallback_disabled_uses_primary():
    """_kickoff_with_retry stays with primary model when budget fallback is disabled."""
    primary_crew = MagicMock()
    primary_crew.kickoff.return_value = "primary-result"
    fallback_crew = MagicMock()
    fallback_crew.kickoff.return_value = "fallback-result"

    metrics = ClaimMetrics()
    metrics.start_claim("CLM-BDF-OFF")
    metrics.record_llm_call(
        claim_id="CLM-BDF-OFF",
        model="gpt-4o-mini",
        input_tokens=4600,
        output_tokens=500,
        cost_usd=0.001,
        latency_ms=100,
        status="success",
    )

    mock_llm_cfg = MagicMock()
    mock_llm_cfg.budget_fallback_enabled = False
    mock_llm_cfg.budget_fallback_threshold = 0.9
    mock_settings = MagicMock()
    mock_settings.llm = mock_llm_cfg

    with (
        patch("claim_agent.workflow.budget.MAX_TOKENS_PER_CLAIM", 5_000),
        patch("claim_agent.workflow.budget.MAX_LLM_CALLS_PER_CLAIM", 50),
        patch("claim_agent.workflow.helpers.get_llm_fallback_chain", return_value=["gpt-4o-mini", "gpt-3.5-turbo"]),
        patch("claim_agent.workflow.helpers._set_model_override"),
        patch("claim_agent.config.settings.get_settings", return_value=mock_settings),
    ):
        result = _kickoff_with_retry(
            primary_crew,
            {},
            create_crew_no_args=lambda: fallback_crew,
            claim_id="CLM-BDF-OFF",
            metrics=metrics,
        )

    assert result == "primary-result"
    primary_crew.kickoff.assert_called_once()
    fallback_crew.kickoff.assert_not_called()


def test_kickoff_with_retry_no_budget_params_uses_primary():
    """_kickoff_with_retry without claim_id/metrics always uses primary model."""
    primary_crew = MagicMock()
    primary_crew.kickoff.return_value = "primary-result"

    with patch("claim_agent.workflow.helpers.get_llm_fallback_chain", return_value=["gpt-4o-mini", "gpt-3.5-turbo"]):
        result = _kickoff_with_retry(primary_crew, {})

    assert result == "primary-result"
    primary_crew.kickoff.assert_called_once()