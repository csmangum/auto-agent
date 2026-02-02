"""Tests for token budget enforcement in main crew."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from claim_agent.crews.main_crew import (
    TokenBudgetExceeded,
    _check_token_budget,
    _record_crew_llm_usage,
)
from claim_agent.observability.metrics import ClaimMetrics, calculate_cost


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


def test_record_crew_llm_usage_records_tokens_and_cost():
    """_record_crew_llm_usage records CrewAI token usage into ClaimMetrics."""
    metrics = ClaimMetrics()
    claim_id = "CLM-RECORD-TEST"
    prompt_tokens = 200
    completion_tokens = 80
    usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        successful_requests=1,
    )
    stub_llm = SimpleNamespace(
        model="gpt-4o-mini",
        get_token_usage_summary=lambda: usage,
    )

    _record_crew_llm_usage(claim_id, stub_llm, metrics)

    summary = metrics.get_claim_summary(claim_id)
    assert summary is not None
    assert summary.total_llm_calls == 1
    assert summary.total_input_tokens == prompt_tokens
    assert summary.total_output_tokens == completion_tokens
    assert summary.total_tokens == prompt_tokens + completion_tokens
    expected_cost = calculate_cost("gpt-4o-mini", prompt_tokens, completion_tokens)
    assert summary.total_cost_usd == expected_cost
    assert "gpt-4o-mini" in summary.models_used


def test_record_crew_llm_usage_prefers_llm_model_over_config():
    """_record_crew_llm_usage uses llm.model when set, not get_model_name()."""
    metrics = ClaimMetrics()
    claim_id = "CLM-CUSTOM-MODEL"
    usage = SimpleNamespace(
        prompt_tokens=10,
        completion_tokens=5,
        successful_requests=1,
    )
    custom_model = "custom/private-model-v1"
    stub_llm = SimpleNamespace(
        model=custom_model,
        get_token_usage_summary=lambda: usage,
    )

    _record_crew_llm_usage(claim_id, stub_llm, metrics)

    summary = metrics.get_claim_summary(claim_id)
    assert summary is not None
    assert summary.models_used == [custom_model]


def test_record_crew_llm_usage_noop_when_no_get_token_usage_summary():
    """_record_crew_llm_usage does nothing when LLM has no get_token_usage_summary."""
    metrics = ClaimMetrics()
    metrics.start_claim("CLM-NO-USAGE")
    stub_llm = SimpleNamespace(model="gpt-4o-mini")  # no get_token_usage_summary

    _record_crew_llm_usage("CLM-NO-USAGE", stub_llm, metrics)

    summary = metrics.get_claim_summary("CLM-NO-USAGE")
    assert summary is not None
    assert summary.total_llm_calls == 0
    assert summary.total_tokens == 0


def test_record_crew_llm_usage_noop_when_zero_tokens():
    """_record_crew_llm_usage does nothing when usage has zero tokens and no successful_requests."""
    metrics = ClaimMetrics()
    claim_id = "CLM-ZERO"
    usage = SimpleNamespace(
        prompt_tokens=0,
        completion_tokens=0,
        successful_requests=0,
    )
    stub_llm = SimpleNamespace(
        model="gpt-4o-mini",
        get_token_usage_summary=lambda: usage,
    )

    _record_crew_llm_usage(claim_id, stub_llm, metrics)

    summary = metrics.get_claim_summary(claim_id)
    assert summary is None
