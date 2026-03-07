"""Tests for centralized configuration (settings)."""

import importlib
import os
from unittest.mock import patch

from claim_agent.config import settings


def test_get_escalation_config_returns_dict():
    """get_escalation_config returns a dict with expected keys."""
    config = settings.get_escalation_config()
    assert isinstance(config, dict)
    assert "confidence_threshold" in config
    assert "high_value_threshold" in config
    assert "similarity_ambiguous_range" in config
    assert "vin_claims_days" in config


def test_get_fraud_config_returns_dict():
    """get_fraud_config returns a dict with expected keys."""
    config = settings.get_fraud_config()
    assert isinstance(config, dict)
    assert "multiple_claims_days" in config
    assert "high_risk_threshold" in config
    assert "critical_risk_threshold" in config


def test_valuation_constants_are_numeric():
    """Valuation constants are numbers."""
    assert isinstance(settings.DEFAULT_BASE_VALUE, (int, float))
    assert isinstance(settings.MIN_PAYOUT_VEHICLE_VALUE, (int, float))
    assert settings.MIN_PAYOUT_VEHICLE_VALUE > 0


def test_token_budget_constants_positive():
    """Token budget constants are positive integers."""
    assert settings.MAX_TOKENS_PER_CLAIM > 0
    assert settings.MAX_LLM_CALLS_PER_CLAIM > 0


def test_get_adapter_backend_default():
    """get_adapter_backend returns 'mock' when env is mock or unset."""
    with patch.dict(os.environ, {"POLICY_ADAPTER": "mock"}):
        assert settings.get_adapter_backend("policy") == "mock"


def test_get_adapter_backend_respects_env():
    """get_adapter_backend reads env and normalizes value."""
    with patch.dict(os.environ, {"POLICY_ADAPTER": "stub"}):
        assert settings.get_adapter_backend("policy") == "stub"
    with patch.dict(os.environ, {"POLICY_ADAPTER": "  MOCK  "}):
        assert settings.get_adapter_backend("policy") == "mock"


def test_get_adapter_backend_blank_treated_as_unset():
    """get_adapter_backend treats blank env var same as unset, returns mock."""
    with patch.dict(os.environ, {"POLICY_ADAPTER": ""}, clear=False):
        assert settings.get_adapter_backend("policy") == "mock"
    with patch.dict(os.environ, {"POLICY_ADAPTER": "   "}, clear=False):
        assert settings.get_adapter_backend("policy") == "mock"


def test_get_crew_verbose_default():
    """get_crew_verbose returns bool."""
    result = settings.get_crew_verbose()
    assert isinstance(result, bool)


def test_get_crew_verbose_respects_env():
    """get_crew_verbose respects CREWAI_VERBOSE env."""
    with patch.dict(os.environ, {"CREWAI_VERBOSE": "false"}):
        assert settings.get_crew_verbose() is False
    with patch.dict(os.environ, {"CREWAI_VERBOSE": "true"}):
        assert settings.get_crew_verbose() is True


class TestEscalationConfigEnvOverrides:
    """Test escalation config reads env overrides."""

    def test_confidence_threshold_override(self):
        with patch.dict(os.environ, {"ESCALATION_CONFIDENCE_THRESHOLD": "0.5"}):
            config = settings.get_escalation_config()
            assert config["confidence_threshold"] == 0.5

    def test_high_value_threshold_override(self):
        with patch.dict(os.environ, {"ESCALATION_HIGH_VALUE_THRESHOLD": "25000"}):
            config = settings.get_escalation_config()
            assert config["high_value_threshold"] == 25000.0

    def test_invalid_float_uses_default(self):
        with patch.dict(os.environ, {"ESCALATION_CONFIDENCE_THRESHOLD": "not-a-number"}):
            config = settings.get_escalation_config()
            assert config["confidence_threshold"] == 0.7


class TestFraudConfigEnvOverrides:
    """Test fraud config reads env overrides."""

    def test_multiple_claims_days_override(self):
        with patch.dict(os.environ, {"FRAUD_MULTIPLE_CLAIMS_DAYS": "60"}):
            config = settings.get_fraud_config()
            assert config["multiple_claims_days"] == 60

    def test_high_risk_threshold_override(self):
        with patch.dict(os.environ, {"FRAUD_HIGH_RISK_THRESHOLD": "40"}):
            config = settings.get_fraud_config()
            assert config["high_risk_threshold"] == 40

    def test_invalid_int_uses_default(self):
        with patch.dict(os.environ, {"FRAUD_MULTIPLE_CLAIMS_DAYS": "invalid"}):
            config = settings.get_fraud_config()
            assert config["multiple_claims_days"] == 90


class TestSimilarityAmbiguousRange:
    """Test _tuple_float for similarity range."""

    def test_valid_tuple_override(self):
        with patch.dict(os.environ, {"ESCALATION_SIMILARITY_AMBIGUOUS_RANGE": "40,90"}):
            config = settings.get_escalation_config()
            assert config["similarity_ambiguous_range"] == (40.0, 90.0)

    def test_invalid_tuple_uses_default(self):
        with patch.dict(os.environ, {"ESCALATION_SIMILARITY_AMBIGUOUS_RANGE": "single"}):
            config = settings.get_escalation_config()
            assert config["similarity_ambiguous_range"] == (50.0, 80.0)


class TestTokenBudgetEnvOverrides:
    """Test token budget constants read env (requires module reload)."""

    def test_max_tokens_override(self):
        try:
            with patch.dict(os.environ, {"CLAIM_AGENT_MAX_TOKENS_PER_CLAIM": "200000"}):
                importlib.reload(settings)
                assert settings.MAX_TOKENS_PER_CLAIM == 200000
        finally:
            importlib.reload(settings)

    def test_max_llm_calls_override(self):
        try:
            with patch.dict(os.environ, {"CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM": "100"}):
                importlib.reload(settings)
                assert settings.MAX_LLM_CALLS_PER_CLAIM == 100
        finally:
            importlib.reload(settings)
