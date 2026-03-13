"""Tests for centralized configuration (settings)."""

import os
from unittest.mock import patch

import pytest

from claim_agent.config import reload_settings
from claim_agent.config import settings


def test_get_escalation_config_returns_dict():
    """get_escalation_config returns a dict with expected keys."""
    config = settings.get_escalation_config()
    assert isinstance(config, dict)
    assert "confidence_threshold" in config
    assert "high_value_threshold" in config
    assert "similarity_ambiguous_range" in config
    assert "vin_claims_days" in config


def test_get_router_config_returns_dict():
    """get_router_config returns a dict with expected keys."""
    config = settings.get_router_config()
    assert isinstance(config, dict)
    assert "confidence_threshold" in config
    assert "validation_enabled" in config
    assert config["confidence_threshold"] == 0.7
    assert config["validation_enabled"] is False


def test_get_router_config_respects_env():
    """get_router_config reads ROUTER_CONFIDENCE_THRESHOLD and ROUTER_VALIDATION_ENABLED."""
    with patch.dict(os.environ, {"ROUTER_CONFIDENCE_THRESHOLD": "0.5", "ROUTER_VALIDATION_ENABLED": "true"}):
        reload_settings()
        config = settings.get_router_config()
        assert config["confidence_threshold"] == 0.5
        assert config["validation_enabled"] is True


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
        reload_settings()
        assert settings.get_adapter_backend("policy") == "mock"


def test_get_adapter_backend_respects_env():
    """get_adapter_backend reads env and normalizes value."""
    with patch.dict(os.environ, {"POLICY_ADAPTER": "stub"}):
        reload_settings()
        assert settings.get_adapter_backend("policy") == "stub"
    with patch.dict(os.environ, {"POLICY_ADAPTER": "  MOCK  "}):
        reload_settings()
        assert settings.get_adapter_backend("policy") == "mock"


def test_get_adapter_backend_blank_treated_as_unset():
    """get_adapter_backend treats blank env var same as unset, returns mock."""
    with patch.dict(os.environ, {"POLICY_ADAPTER": ""}, clear=False):
        reload_settings()
        assert settings.get_adapter_backend("policy") == "mock"
    with patch.dict(os.environ, {"POLICY_ADAPTER": "   "}, clear=False):
        reload_settings()
        assert settings.get_adapter_backend("policy") == "mock"


def test_get_crew_verbose_default():
    """get_crew_verbose returns bool."""
    result = settings.get_crew_verbose()
    assert isinstance(result, bool)


def test_get_crew_verbose_respects_env():
    """get_crew_verbose respects CREWAI_VERBOSE env."""
    with patch.dict(os.environ, {"CREWAI_VERBOSE": "false"}):
        reload_settings()
        assert settings.get_crew_verbose() is False
    with patch.dict(os.environ, {"CREWAI_VERBOSE": "true"}):
        reload_settings()
        assert settings.get_crew_verbose() is True


def test_get_webhook_config_returns_dict():
    """get_webhook_config returns dict with urls, secret, max_retries, enabled."""
    config = settings.get_webhook_config()
    assert isinstance(config, dict)
    assert "urls" in config
    assert "secret" in config
    assert "max_retries" in config
    assert "enabled" in config


def test_get_notification_config_returns_dict():
    """get_notification_config returns dict with email_enabled, sms_enabled."""
    config = settings.get_notification_config()
    assert isinstance(config, dict)
    assert "email_enabled" in config
    assert "sms_enabled" in config


class TestEscalationConfigEnvOverrides:
    """Test escalation config reads env overrides."""

    def test_confidence_threshold_override(self):
        with patch.dict(os.environ, {"ESCALATION_CONFIDENCE_THRESHOLD": "0.5"}):
            reload_settings()
            config = settings.get_escalation_config()
            assert config["confidence_threshold"] == 0.5

    def test_high_value_threshold_override(self):
        with patch.dict(os.environ, {"ESCALATION_HIGH_VALUE_THRESHOLD": "25000"}):
            reload_settings()
            config = settings.get_escalation_config()
            assert config["high_value_threshold"] == 25000.0

    def test_invalid_float_uses_default(self):
        with patch.dict(os.environ, {"ESCALATION_CONFIDENCE_THRESHOLD": "not-a-number"}):
            reload_settings()
            config = settings.get_escalation_config()
            assert config["confidence_threshold"] == 0.7


class TestFraudConfigEnvOverrides:
    """Test fraud config reads env overrides."""

    def test_multiple_claims_days_override(self):
        with patch.dict(os.environ, {"FRAUD_MULTIPLE_CLAIMS_DAYS": "60"}):
            reload_settings()
            config = settings.get_fraud_config()
            assert config["multiple_claims_days"] == 60

    def test_high_risk_threshold_override(self):
        with patch.dict(os.environ, {"FRAUD_HIGH_RISK_THRESHOLD": "40"}):
            reload_settings()
            config = settings.get_fraud_config()
            assert config["high_risk_threshold"] == 40

    def test_invalid_int_uses_default(self):
        with patch.dict(os.environ, {"FRAUD_MULTIPLE_CLAIMS_DAYS": "invalid"}):
            reload_settings()
            config = settings.get_fraud_config()
            assert config["multiple_claims_days"] == 90


class TestSimilarityAmbiguousRange:
    """Test _tuple_float for similarity range."""

    def test_valid_tuple_override(self):
        with patch.dict(os.environ, {"ESCALATION_SIMILARITY_AMBIGUOUS_RANGE": "40,90"}):
            reload_settings()
            config = settings.get_escalation_config()
            assert config["similarity_ambiguous_range"] == (40.0, 90.0)

    def test_invalid_tuple_uses_default(self):
        with patch.dict(os.environ, {"ESCALATION_SIMILARITY_AMBIGUOUS_RANGE": "single"}):
            reload_settings()
            config = settings.get_escalation_config()
            assert config["similarity_ambiguous_range"] == (50.0, 80.0)


class TestTokenBudgetEnvOverrides:
    """Test token budget constants read env."""

    def test_max_tokens_override(self):
        with patch.dict(os.environ, {"CLAIM_AGENT_MAX_TOKENS_PER_CLAIM": "200000"}):
            reload_settings()
            assert settings.MAX_TOKENS_PER_CLAIM == 200000

    def test_max_llm_calls_override(self):
        with patch.dict(os.environ, {"CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM": "100"}):
            reload_settings()
            assert settings.MAX_LLM_CALLS_PER_CLAIM == 100


class TestDuplicateAndHighValueConfig:
    """Test duplicate detection and high-value thresholds read env."""

    def test_duplicate_similarity_threshold_defaults(self):
        """Defaults: 40, 60, 3."""
        assert settings.DUPLICATE_SIMILARITY_THRESHOLD == 40
        assert settings.DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE == 60
        assert settings.DUPLICATE_DAYS_WINDOW == 3

    def test_duplicate_config_respects_env(self):
        with patch.dict(
            os.environ,
            {
                "DUPLICATE_SIMILARITY_THRESHOLD": "50",
                "DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE": "70",
                "DUPLICATE_DAYS_WINDOW": "5",
            },
        ):
            reload_settings()
            assert settings.DUPLICATE_SIMILARITY_THRESHOLD == 50
            assert settings.DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE == 70
            assert settings.DUPLICATE_DAYS_WINDOW == 5

    def test_high_value_thresholds_defaults(self):
        assert settings.HIGH_VALUE_DAMAGE_THRESHOLD == 25_000
        assert settings.HIGH_VALUE_VEHICLE_THRESHOLD == 50_000

    def test_escalation_sla_hours_defaults(self):
        assert settings.ESCALATION_SLA_HOURS_CRITICAL == 24
        assert settings.ESCALATION_SLA_HOURS_HIGH == 24
        assert settings.ESCALATION_SLA_HOURS_MEDIUM == 48
        assert settings.ESCALATION_SLA_HOURS_LOW == 72

    def test_pre_routing_fraud_ratio_default(self):
        assert settings.PRE_ROUTING_FRAUD_DAMAGE_RATIO == 0.9


class TestJWTSecretValidation:
    """JWT_SECRET must be >= 32 characters or empty (disabled)."""

    def test_empty_secret_is_allowed(self):
        with patch.dict(os.environ, {"JWT_SECRET": ""}):
            reload_settings()
            assert settings.get_jwt_secret() is None

    def test_long_enough_secret_is_accepted(self):
        secret = "a" * 32
        with patch.dict(os.environ, {"JWT_SECRET": secret}):
            reload_settings()
            assert settings.get_jwt_secret() == secret

    def test_short_secret_raises_validation_error(self):
        from pydantic import ValidationError
        from claim_agent.config.settings_model import AuthConfig

        with pytest.raises(ValidationError, match="at least 32 characters"):
            AuthConfig(jwt_secret_raw="too-short")

    def test_31_char_secret_is_rejected(self):
        from pydantic import ValidationError
        from claim_agent.config.settings_model import AuthConfig

        with pytest.raises(ValidationError, match="at least 32 characters"):
            AuthConfig(jwt_secret_raw="a" * 31)

    def test_32_char_secret_is_accepted(self):
        from claim_agent.config.settings_model import AuthConfig

        config = AuthConfig(jwt_secret_raw="b" * 32)
        assert config.jwt_secret == "b" * 32


def test_get_mock_crew_config_returns_dict():
    """get_mock_crew_config returns dict with enabled and seed."""
    config = settings.get_mock_crew_config()
    assert isinstance(config, dict)
    assert "enabled" in config
    assert "seed" in config
    assert config["enabled"] is False
    assert config["seed"] is None


def test_get_mock_crew_config_respects_env():
    """get_mock_crew_config reads MOCK_CREW_ENABLED and MOCK_CREW_SEED."""
    with patch.dict(
        os.environ,
        {"MOCK_CREW_ENABLED": "true", "MOCK_CREW_SEED": "42"},
        clear=False,
    ):
        reload_settings()
        config = settings.get_mock_crew_config()
        assert config["enabled"] is True
        assert config["seed"] == 42


def test_get_mock_image_config_returns_dict():
    """get_mock_image_config returns dict with expected keys."""
    config = settings.get_mock_image_config()
    assert isinstance(config, dict)
    assert "generator_enabled" in config
    assert "model" in config
    assert "vision_analysis_source" in config
    assert config["generator_enabled"] is False
    assert "gemini" in config["model"].lower() or "flash" in config["model"].lower()


def test_get_adapter_backend_vision_default():
    """get_adapter_backend returns 'real' for vision when unset."""
    with patch.dict(os.environ, {"VISION_ADAPTER": ""}, clear=False):
        reload_settings()
        assert settings.get_adapter_backend("vision") == "real"


def test_get_adapter_backend_vision_mock():
    """get_adapter_backend returns 'mock' for vision when VISION_ADAPTER=mock."""
    with patch.dict(os.environ, {"VISION_ADAPTER": "mock"}):
        reload_settings()
        assert settings.get_adapter_backend("vision") == "mock"


def test_get_adapter_backend_vision_invalid_falls_back_to_real():
    """get_adapter_backend returns 'real' for vision when value is invalid."""
    with patch.dict(os.environ, {"VISION_ADAPTER": "stub"}):
        reload_settings()
        assert settings.get_adapter_backend("vision") == "real"
