"""Tests for mock crew claimant: generate_claim_input and respond_to_message."""

from datetime import date
from unittest.mock import patch

import pytest

from claim_agent.mock_crew.claimant import generate_claim_input, respond_to_message


class TestGenerateClaimInput:
    """Tests for generate_claim_input."""

    def _patch_seed(self, seed=None):
        return patch(
            "claim_agent.mock_crew.claimant.get_mock_crew_config",
            return_value={"enabled": True, "seed": seed},
        )

    def test_minimal_scenario_returns_required_fields(self):
        """Empty scenario produces all required ClaimInput fields."""
        with self._patch_seed(42):
            result = generate_claim_input({})

        required = [
            "policy_number",
            "vin",
            "vehicle_year",
            "vehicle_make",
            "vehicle_model",
            "incident_date",
            "incident_description",
            "damage_description",
        ]
        for field in required:
            assert field in result, f"Missing required field: {field}"

    def test_defaults_are_sensible(self):
        """Default values fall back to template vehicle and recent incident date."""
        with self._patch_seed(0):
            result = generate_claim_input({})

        assert result["policy_number"] == "POL-001"
        assert result["vin"] == "1HGBH41JXMN109186"
        assert result["vehicle_make"] == "Honda"
        assert result["vehicle_model"] == "Accord"
        assert result["vehicle_year"] == 2021
        # Date should be a valid ISO string and in the past
        incident_date = date.fromisoformat(result["incident_date"])
        assert incident_date <= date.today()

    def test_scenario_vehicle_overrides_defaults(self):
        """Vehicle fields from scenario override defaults."""
        scenario = {
            "vehicle": {
                "vin": "5YJSA1E26HF999999",
                "year": 2023,
                "make": "Tesla",
                "model": "Model Y",
            }
        }
        with self._patch_seed(1):
            result = generate_claim_input(scenario)

        assert result["vin"] == "5YJSA1E26HF999999"
        assert result["vehicle_year"] == 2023
        assert result["vehicle_make"] == "Tesla"
        assert result["vehicle_model"] == "Model Y"

    def test_scenario_policy_overrides_default(self):
        """policy.policy_number from scenario is used."""
        scenario = {"policy": {"policy_number": "POL-007"}}
        with self._patch_seed(2):
            result = generate_claim_input(scenario)

        assert result["policy_number"] == "POL-007"

    def test_scenario_incident_overrides_defaults(self):
        """Incident date, description, location, and loss_state from scenario are used."""
        scenario = {
            "incident": {
                "date": "2025-06-15",
                "description": "Hit a deer on the highway.",
                "location": "I-35, Austin, TX",
                "loss_state": "TX",
            }
        }
        with self._patch_seed(3):
            result = generate_claim_input(scenario)

        assert result["incident_date"] == "2025-06-15"
        assert result["incident_description"] == "Hit a deer on the highway."
        assert result["incident_location"] == "I-35, Austin, TX"
        assert result["loss_state"] == "TX"

    def test_scenario_damage_overrides_defaults(self):
        """Damage description and estimated_damage from scenario are used."""
        scenario = {
            "damage": {
                "description": "Total loss: frame bent beyond repair.",
                "estimated_damage": 18000.0,
            }
        }
        with self._patch_seed(4):
            result = generate_claim_input(scenario)

        assert result["damage_description"] == "Total loss: frame bent beyond repair."
        assert result["estimated_damage"] == pytest.approx(18000.0)

    def test_negative_estimated_damage_excluded(self):
        """Negative estimated_damage is silently dropped (set to None)."""
        scenario = {"damage": {"estimated_damage": -500.0}}
        with self._patch_seed(5):
            result = generate_claim_input(scenario)

        assert "estimated_damage" not in result

    def test_claim_type_included_when_provided(self):
        """claim_type from scenario is included in result."""
        scenario = {"claim_type": "total_loss"}
        with self._patch_seed(6):
            result = generate_claim_input(scenario)

        assert result["claim_type"] == "total_loss"

    def test_claim_type_absent_when_not_provided(self):
        """claim_type is absent from result when not in scenario."""
        with self._patch_seed(7):
            result = generate_claim_input({})

        assert "claim_type" not in result

    def test_optional_location_absent_when_not_provided(self):
        """incident_location is absent from result when not in scenario."""
        with self._patch_seed(8):
            result = generate_claim_input({})

        assert "incident_location" not in result

    def test_deterministic_with_seed(self):
        """Same seed produces same output."""
        with self._patch_seed(99):
            r1 = generate_claim_input({})
        with self._patch_seed(99):
            r2 = generate_claim_input({})

        assert r1 == r2

    def test_full_scenario(self):
        """Full scenario with all keys produces a clean result."""
        scenario = {
            "claim_type": "partial_loss",
            "policy": {"policy_number": "POL-010"},
            "vehicle": {"vin": "ABC123", "year": 2020, "make": "Ford", "model": "F-150"},
            "incident": {
                "date": "2026-01-10",
                "description": "Side-swiped on highway.",
                "location": "Highway 1, CA",
                "loss_state": "CA",
            },
            "damage": {
                "description": "Passenger side door and quarter panel dented.",
                "estimated_damage": 4500.0,
            },
        }
        with self._patch_seed(0):
            result = generate_claim_input(scenario)

        assert result["policy_number"] == "POL-010"
        assert result["vin"] == "ABC123"
        assert result["vehicle_year"] == 2020
        assert result["claim_type"] == "partial_loss"
        assert result["loss_state"] == "CA"
        assert result["estimated_damage"] == pytest.approx(4500.0)


class TestRespondToMessage:
    """Tests for respond_to_message."""

    def _patch_strategy(self, strategy="immediate"):
        return patch(
            "claim_agent.mock_crew.claimant.get_mock_claimant_config",
            return_value={"enabled": True, "response_strategy": strategy},
        )

    def test_photo_request_acknowledged(self):
        """Messages mentioning photos trigger an upload acknowledgment."""
        for phrase in ["send photos", "please upload pictures", "attach images"]:
            with self._patch_strategy("immediate"):
                reply = respond_to_message("CLM-001", phrase, {})
            assert "portal" in reply.lower() or "photo" in reply.lower()

    def test_estimate_request_acknowledged(self):
        """Messages mentioning estimate/shop trigger a shop estimate response."""
        for phrase in ["can you get an estimate", "take it to a repair shop", "body shop quote"]:
            with self._patch_strategy("immediate"):
                reply = respond_to_message("CLM-001", phrase, {})
            assert "estimate" in reply.lower() or "shop" in reply.lower()

    def test_police_report_request(self):
        """Messages about police report trigger appropriate response."""
        with self._patch_strategy("immediate"):
            reply = respond_to_message("CLM-001", "please provide the police report", {})
        assert "police" in reply.lower() or "report" in reply.lower()

    def test_generic_fallback(self):
        """Unrecognised messages get a generic deferral reply."""
        with self._patch_strategy("immediate"):
            reply = respond_to_message("CLM-001", "What is the weather today?", {})
        assert len(reply) > 0
        assert "shortly" in reply.lower() or "provide" in reply.lower()

    def test_strategy_refuse(self):
        """'refuse' strategy always returns the refuse message."""
        with self._patch_strategy("refuse"):
            reply = respond_to_message("CLM-001", "send photos please", {})
        assert "not able to provide" in reply.lower()

    def test_strategy_delayed(self):
        """'delayed' strategy returns the delayed message regardless of content."""
        with self._patch_strategy("delayed"):
            reply = respond_to_message("CLM-001", "send photos please", {})
        assert "business day" in reply.lower() or "time" in reply.lower()

    def test_strategy_partial(self):
        """'partial' strategy returns the partial response message."""
        with self._patch_strategy("partial"):
            reply = respond_to_message("CLM-001", "give me everything", {})
        assert "part" in reply.lower() or "follow up" in reply.lower()

    def test_claim_context_does_not_break_generic(self):
        """Passing a claim_context dict doesn't break generic replies."""
        ctx = {
            "vehicle": {"year": 2022, "make": "Toyota", "model": "Camry"},
            "incident": {"description": "rear-end collision"},
        }
        with self._patch_strategy("immediate"):
            reply = respond_to_message("CLM-002", "unrelated question", ctx)
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_medical_request_with_vehicle_context(self):
        """Medical records request uses vehicle context when available."""
        ctx = {"vehicle": {"year": 2021, "make": "Honda", "model": "Accord"}}
        with self._patch_strategy("immediate"):
            reply = respond_to_message("CLM-003", "please provide medical records", ctx)
        assert "medical" in reply.lower() or "doctor" in reply.lower()

    def test_contact_information_request(self):
        """Messages about contact info produce an appropriate reply."""
        with self._patch_strategy("immediate"):
            reply = respond_to_message("CLM-004", "Can you provide your phone number?", {})
        assert "contact" in reply.lower() or "reach" in reply.lower() or "file" in reply.lower()


class TestGetMockClaimantConfig:
    """Tests for the config helper."""

    def test_defaults(self):
        """Default config returns enabled=False, strategy=immediate."""
        from unittest.mock import patch as _patch

        from claim_agent.config.settings import get_mock_claimant_config

        with _patch.dict("os.environ", {}, clear=False):
            # Force reload so env overrides take effect
            from claim_agent.config import reload_settings

            reload_settings()
            cfg = get_mock_claimant_config()

        assert cfg["enabled"] is False
        assert cfg["response_strategy"] == "immediate"

    def test_env_overrides(self):
        """Env vars override default config values."""
        import os
        from unittest.mock import patch as _patch

        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_mock_claimant_config

        env_overrides = {
            "MOCK_CLAIMANT_ENABLED": "true",
            "MOCK_CLAIMANT_RESPONSE_STRATEGY": "refuse",
        }
        with _patch.dict(os.environ, env_overrides):
            reload_settings()
            cfg = get_mock_claimant_config()

        assert cfg["enabled"] is True
        assert cfg["response_strategy"] == "refuse"

        # Restore defaults
        reload_settings()

    def test_invalid_strategy_falls_back_to_immediate(self):
        """Unknown response_strategy falls back to 'immediate'."""
        import os
        from unittest.mock import patch as _patch

        from claim_agent.config import reload_settings
        from claim_agent.config.settings import get_mock_claimant_config

        with _patch.dict(os.environ, {"MOCK_CLAIMANT_RESPONSE_STRATEGY": "bogus"}):
            reload_settings()
            cfg = get_mock_claimant_config()

        assert cfg["response_strategy"] == "immediate"

        reload_settings()
