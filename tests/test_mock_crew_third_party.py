"""Tests for mock third party: mock_send_demand_letter and send_demand_letter_impl integration."""

import json
import logging
from unittest.mock import patch

import pytest

from claim_agent.config.settings_model import MockThirdPartyConfig, ThirdPartyOutcome
from claim_agent.mock_crew.third_party import mock_send_demand_letter
from claim_agent.tools.subrogation_logic import send_demand_letter_impl
from tests.conftest import LogCaptureHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_CREW_ON = {"enabled": True, "seed": None}
_MOCK_CREW_OFF = {"enabled": False, "seed": None}
_MOCK_THIRD_PARTY_ACCEPT = {"enabled": True, "outcome": "accept"}
_MOCK_THIRD_PARTY_REJECT = {"enabled": True, "outcome": "reject"}
_MOCK_THIRD_PARTY_NEGOTIATE = {"enabled": True, "outcome": "negotiate"}
_MOCK_THIRD_PARTY_OFF = {"enabled": False, "outcome": "accept"}


# ---------------------------------------------------------------------------
# Tests for mock_send_demand_letter
# ---------------------------------------------------------------------------


class TestMockSendDemandLetter:
    """Unit tests for mock_send_demand_letter()."""

    def test_accept_outcome_contains_expected_fields(self):
        """Accept outcome should confirm full payment."""
        with patch(
            "claim_agent.mock_crew.third_party.get_mock_third_party_config",
            return_value=_MOCK_THIRD_PARTY_ACCEPT,
        ):
            response = mock_send_demand_letter("SUB-001", "CLM-001", 5000.0)

        assert response["third_party_response"] == "accept"
        assert "third_party_message" in response
        assert response["counter_amount"] is None

    def test_reject_outcome_contains_expected_fields(self):
        """Reject outcome should deny the demand."""
        with patch(
            "claim_agent.mock_crew.third_party.get_mock_third_party_config",
            return_value=_MOCK_THIRD_PARTY_REJECT,
        ):
            response = mock_send_demand_letter("SUB-002", "CLM-002", 3000.0)

        assert response["third_party_response"] == "reject"
        assert "third_party_message" in response
        assert response["counter_amount"] is None

    def test_negotiate_outcome_computes_counter_amount(self):
        """Negotiate outcome should compute counter_amount as 60% of amount_sought."""
        with patch(
            "claim_agent.mock_crew.third_party.get_mock_third_party_config",
            return_value=_MOCK_THIRD_PARTY_NEGOTIATE,
        ):
            response = mock_send_demand_letter("SUB-003", "CLM-003", 4000.0)

        assert response["third_party_response"] == "negotiate"
        assert response["counter_amount"] == pytest.approx(2400.0)
        assert "counter_amount_ratio" not in response

    def test_negotiate_rounds_counter_amount_to_cents(self):
        """counter_amount should be rounded to 2 decimal places."""
        with patch(
            "claim_agent.mock_crew.third_party.get_mock_third_party_config",
            return_value=_MOCK_THIRD_PARTY_NEGOTIATE,
        ):
            response = mock_send_demand_letter("SUB-004", "CLM-004", 3333.33)

        # 3333.33 * 0.6 = 1999.998 → 2000.0
        assert response["counter_amount"] == pytest.approx(2000.0, abs=0.01)

    def test_logs_interception_at_info(self):
        """mock_send_demand_letter should log at INFO level."""
        log = logging.getLogger("claim_agent.mock_crew.third_party")
        cap = LogCaptureHandler()
        cap.setLevel(logging.INFO)
        prev_level = log.level
        log.addHandler(cap)
        log.setLevel(logging.INFO)
        try:
            with patch(
                "claim_agent.mock_crew.third_party.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_ACCEPT,
            ):
                mock_send_demand_letter("SUB-005", "CLM-005", 1000.0)
        finally:
            log.removeHandler(cap)
            log.setLevel(prev_level)

        assert any("CLM-005" in m for m in cap.messages)
        assert any("accept" in m for m in cap.messages)


# ---------------------------------------------------------------------------
# Tests for send_demand_letter_impl integration
# ---------------------------------------------------------------------------


class TestSendDemandLetterImplMockIntegration:
    """Integration tests: send_demand_letter_impl with mock third party enabled."""

    def test_mock_enabled_adds_third_party_response_to_result(self):
        """When mock third party is enabled, result includes third_party_response."""
        with (
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_ACCEPT,
            ),
            patch(
                "claim_agent.mock_crew.third_party.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_ACCEPT,
            ),
        ):
            raw = send_demand_letter_impl("SUB-INT01", "CLM-INT01", 8000.0)

        result = json.loads(raw)
        assert result["status"] == "demand_sent"
        assert result["third_party_response"] == "accept"
        assert "letter_id" in result
        assert result["claim_id"] == "CLM-INT01"

    def test_mock_enabled_reject_outcome(self):
        """Reject outcome is propagated correctly through send_demand_letter_impl."""
        with (
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_REJECT,
            ),
            patch(
                "claim_agent.mock_crew.third_party.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_REJECT,
            ),
        ):
            raw = send_demand_letter_impl("SUB-INT02", "CLM-INT02", 6000.0)

        result = json.loads(raw)
        assert result["third_party_response"] == "reject"

    def test_mock_enabled_negotiate_outcome_has_counter_amount(self):
        """Negotiate outcome includes counter_amount in the result."""
        with (
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_NEGOTIATE,
            ),
            patch(
                "claim_agent.mock_crew.third_party.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_NEGOTIATE,
            ),
        ):
            raw = send_demand_letter_impl("SUB-INT03", "CLM-INT03", 5000.0)

        result = json.loads(raw)
        assert result["third_party_response"] == "negotiate"
        assert result["counter_amount"] == pytest.approx(3000.0)

    def test_mock_disabled_returns_standard_stub(self):
        """When mock third party is disabled, result has no third_party_response key."""
        with (
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_crew_config",
                return_value=_MOCK_CREW_ON,
            ),
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_OFF,
            ),
        ):
            raw = send_demand_letter_impl("SUB-INT04", "CLM-INT04", 7000.0)

        result = json.loads(raw)
        assert "third_party_response" not in result
        assert result["status"] == "demand_sent"
        assert result["confirmation"] == "Demand letter generated and sent (mock)."

    def test_mock_crew_off_returns_standard_stub(self):
        """When MOCK_CREW_ENABLED=false, no third-party intercept occurs."""
        with (
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_crew_config",
                return_value=_MOCK_CREW_OFF,
            ),
            patch(
                "claim_agent.tools.subrogation_logic.get_mock_third_party_config",
                return_value=_MOCK_THIRD_PARTY_ACCEPT,
            ),
        ):
            raw = send_demand_letter_impl("SUB-INT05", "CLM-INT05", 4000.0)

        result = json.loads(raw)
        assert "third_party_response" not in result
        assert result["status"] == "demand_sent"


# ---------------------------------------------------------------------------
# Tests for ThirdPartyOutcome validator fallback
# ---------------------------------------------------------------------------


class TestThirdPartyOutcomeValidator:
    """Tests for MockThirdPartyConfig._parse_outcome validator."""

    def test_invalid_outcome_falls_back_to_accept(self):
        """An unrecognized outcome value should silently fall back to 'accept'."""
        cfg = MockThirdPartyConfig(
            MOCK_THIRD_PARTY_ENABLED="true",
            MOCK_THIRD_PARTY_OUTCOME="invalid_value",
        )
        assert cfg.outcome == ThirdPartyOutcome.ACCEPT

    def test_empty_outcome_falls_back_to_accept(self):
        """An empty string outcome should fall back to 'accept'."""
        cfg = MockThirdPartyConfig(
            MOCK_THIRD_PARTY_ENABLED="true",
            MOCK_THIRD_PARTY_OUTCOME="",
        )
        assert cfg.outcome == ThirdPartyOutcome.ACCEPT

    def test_valid_outcomes_are_accepted(self):
        """All valid outcome values should be parsed correctly."""
        for value in ("accept", "reject", "negotiate"):
            cfg = MockThirdPartyConfig(
                MOCK_THIRD_PARTY_ENABLED="true",
                MOCK_THIRD_PARTY_OUTCOME=value,
            )
            assert cfg.outcome.value == value

    def test_case_insensitive_outcome(self):
        """Outcome parsing should be case-insensitive."""
        cfg = MockThirdPartyConfig(
            MOCK_THIRD_PARTY_ENABLED="true",
            MOCK_THIRD_PARTY_OUTCOME="NEGOTIATE",
        )
        assert cfg.outcome == ThirdPartyOutcome.NEGOTIATE


# ---------------------------------------------------------------------------
# Tests for mock_send_demand_letter with unknown outcome
# ---------------------------------------------------------------------------


class TestMockSendDemandLetterUnknownOutcome:
    """Tests for mock_send_demand_letter when config returns unrecognized outcome."""

    def test_unknown_outcome_falls_back_to_accept(self):
        """If config somehow returns an unrecognized outcome, fall back to accept."""
        unknown_config = {"enabled": True, "outcome": "unknown_value"}
        with patch(
            "claim_agent.mock_crew.third_party.get_mock_third_party_config",
            return_value=unknown_config,
        ):
            response = mock_send_demand_letter("SUB-UNK", "CLM-UNK", 5000.0)

        assert response["third_party_response"] == "accept"
        assert response["counter_amount"] is None
