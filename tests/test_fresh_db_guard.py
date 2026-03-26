"""Unit tests for the FRESH_CLAIMS_DB_ON_STARTUP startup guard."""

import logging

import pytest

from claim_agent.config import reload_settings


class TestCheckFreshDbConfiguration:
    """Tests for the _check_fresh_db_configuration server startup guard."""

    def _check(self):
        from claim_agent.api.server import _check_fresh_db_configuration

        _check_fresh_db_configuration()

    # ------------------------------------------------------------------
    # Flag disabled — guard should always pass regardless of environment
    # ------------------------------------------------------------------

    def test_passes_when_flag_disabled_in_dev(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "false")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "development")
        reload_settings()
        self._check()  # should not raise

    def test_passes_when_flag_disabled_in_production(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "false")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "production")
        reload_settings()
        self._check()  # should not raise

    # ------------------------------------------------------------------
    # Flag enabled in dev environments — always allowed
    # ------------------------------------------------------------------

    def test_passes_when_flag_enabled_in_dev(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "development")
        reload_settings()
        self._check()  # should not raise

    def test_passes_when_flag_enabled_in_dev_shorthand(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "dev")
        reload_settings()
        self._check()  # should not raise

    def test_passes_when_flag_enabled_in_test(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "test")
        reload_settings()
        self._check()  # should not raise

    def test_passes_when_flag_enabled_in_testing(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "testing")
        reload_settings()
        self._check()  # should not raise

    # ------------------------------------------------------------------
    # Flag enabled in non-dev environments — should raise without override
    # ------------------------------------------------------------------

    def test_raises_in_production_without_override(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("FRESH_CLAIMS_DB_NON_DEV_OVERRIDE", "false")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "production")
        reload_settings()
        with pytest.raises(RuntimeError, match="FRESH_CLAIMS_DB_ON_STARTUP=true is not allowed"):
            self._check()

    def test_raises_in_staging_without_override(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("FRESH_CLAIMS_DB_NON_DEV_OVERRIDE", "false")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "staging")
        reload_settings()
        with pytest.raises(RuntimeError, match="FRESH_CLAIMS_DB_ON_STARTUP=true is not allowed"):
            self._check()

    def test_error_message_contains_environment_name(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("FRESH_CLAIMS_DB_NON_DEV_OVERRIDE", "false")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "production")
        reload_settings()
        with pytest.raises(RuntimeError, match="production"):
            self._check()

    def test_error_message_mentions_override_flag(self, monkeypatch):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("FRESH_CLAIMS_DB_NON_DEV_OVERRIDE", "false")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "production")
        reload_settings()
        with pytest.raises(RuntimeError, match="FRESH_CLAIMS_DB_NON_DEV_OVERRIDE"):
            self._check()

    # ------------------------------------------------------------------
    # Flag enabled in non-dev with override — should warn but not raise
    # ------------------------------------------------------------------

    def test_passes_with_override_in_production_and_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("FRESH_CLAIMS_DB_NON_DEV_OVERRIDE", "true")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "production")
        reload_settings()
        with caplog.at_level(logging.WARNING, logger="claim_agent.api.server"):
            self._check()  # should not raise
        assert any(
            "FRESH_CLAIMS_DB_ON_STARTUP=true is active in a non-development environment" in m
            for m in caplog.messages
        )

    def test_passes_with_override_in_staging_and_warns(self, monkeypatch, caplog):
        monkeypatch.setenv("FRESH_CLAIMS_DB_ON_STARTUP", "true")
        monkeypatch.setenv("FRESH_CLAIMS_DB_NON_DEV_OVERRIDE", "true")
        monkeypatch.setenv("CLAIM_AGENT_ENVIRONMENT", "staging")
        reload_settings()
        with caplog.at_level(logging.WARNING, logger="claim_agent.api.server"):
            self._check()  # should not raise
        assert any(
            "FRESH_CLAIMS_DB_NON_DEV_OVERRIDE=true" in m for m in caplog.messages
        )
