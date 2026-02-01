"""Tests for centralized configuration (settings)."""

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
