"""Tests for mock crew claim generator."""

from unittest.mock import patch

import pytest

from claim_agent.mock_crew.claim_generator import (
    _extract_json,
    _pick_policy_and_vehicle,
    _vehicle_filter_from_prompt,
    generate_claim_from_prompt,
    generate_incident_damage_from_vehicle,
)


class TestExtractJson:
    """Tests for _extract_json."""

    def test_extracts_raw_json_object(self):
        """Extracts dict from raw JSON string."""
        text = '{"incident_date": "2025-01-15", "damage_description": "bumper dent"}'
        result = _extract_json(text)
        assert result == {
            "incident_date": "2025-01-15",
            "damage_description": "bumper dent",
        }

    def test_extracts_from_markdown_code_block(self):
        """Extracts JSON from ```json ... ``` block."""
        text = """Here is the result:
```json
{"incident_date": "2025-01-10", "estimated_damage": 1500}
```
"""
        result = _extract_json(text)
        assert result == {
            "incident_date": "2025-01-10",
            "estimated_damage": 1500,
        }

    def test_extracts_first_brace_delimited_object(self):
        """Extracts first {...} object when not valid top-level JSON."""
        text = 'Some text {"incident_date": "2025-01-01", "notes": "ok"} more text'
        result = _extract_json(text)
        assert result == {"incident_date": "2025-01-01", "notes": "ok"}

    def test_returns_none_for_empty_string(self):
        """Empty or whitespace returns None."""
        assert _extract_json("") is None
        assert _extract_json("   ") is None

    def test_returns_none_for_invalid_json(self):
        """Invalid JSON returns None."""
        assert _extract_json("not json at all") is None
        assert _extract_json("{invalid}") is None

    def test_returns_none_for_non_dict_json(self):
        """JSON array or primitive returns None."""
        assert _extract_json("[1, 2, 3]") is None
        assert _extract_json("42") is None


class TestVehicleFilterFromPrompt:
    """Tests for _vehicle_filter_from_prompt."""

    def test_extracts_honda(self):
        """Honda in prompt returns Honda."""
        assert _vehicle_filter_from_prompt("Honda Accord fender bender") == "Honda"

    def test_extracts_tesla(self):
        """Tesla in prompt returns Tesla."""
        assert _vehicle_filter_from_prompt("Tesla Model 3 flood") == "Tesla"

    def test_extracts_model_3(self):
        """model 3 in prompt returns Model 3 (title case)."""
        assert _vehicle_filter_from_prompt("model 3 accident") == "Model 3"

    def test_returns_none_when_no_vehicle_mentioned(self):
        """Generic prompt returns None."""
        assert _vehicle_filter_from_prompt("parking lot accident") is None


class TestPickPolicyAndVehicle:
    """Tests for _pick_policy_and_vehicle with mocked load_mock_db."""

    def test_picks_policy_and_vehicle_with_collision(self):
        """Picks from active policies with collision and policy_vehicles."""
        mock_db = {
            "policies": {
                "POL-A": {"status": "active", "coverages": ["liability", "collision"]},
            },
            "policy_vehicles": {
                "POL-A": [
                    {
                        "vin": "VIN123",
                        "vehicle_year": 2021,
                        "vehicle_make": "Honda",
                        "vehicle_model": "Accord",
                    },
                ],
            },
        }
        with patch(
            "claim_agent.mock_crew.claim_generator.load_mock_db",
            return_value=mock_db,
        ):
            pn, vehicle = _pick_policy_and_vehicle(seed=42)
        assert pn == "POL-A"
        assert vehicle["vin"] == "VIN123"
        assert vehicle["vehicle_make"] == "Honda"
        assert vehicle["vehicle_model"] == "Accord"

    def test_filters_by_vehicle_when_specified(self):
        """When vehicle_filter given, only matching vehicles considered."""
        mock_db = {
            "policies": {
                "POL-A": {"status": "active", "coverages": ["collision"]},
                "POL-B": {"status": "active", "coverages": ["collision"]},
            },
            "policy_vehicles": {
                "POL-A": [
                    {"vin": "V1", "vehicle_year": 2020, "vehicle_make": "Toyota", "vehicle_model": "Camry"},
                ],
                "POL-B": [
                    {"vin": "V2", "vehicle_year": 2021, "vehicle_make": "Honda", "vehicle_model": "Accord"},
                ],
            },
        }
        with patch(
            "claim_agent.mock_crew.claim_generator.load_mock_db",
            return_value=mock_db,
        ):
            pn, vehicle = _pick_policy_and_vehicle(vehicle_filter="Honda", seed=99)
        assert vehicle["vehicle_make"] == "Honda"

    def test_raises_when_no_candidates(self):
        """Raises when no active policies with collision and vehicles."""
        mock_db = {
            "policies": {
                "POL-A": {"status": "active", "coverages": ["liability"]},
            },
            "policy_vehicles": {},
        }
        with patch(
            "claim_agent.mock_crew.claim_generator.load_mock_db",
            return_value=mock_db,
        ):
            with pytest.raises(ValueError, match="No active policies"):
                _pick_policy_and_vehicle()


class TestGenerateClaimFromPrompt:
    """Tests for generate_claim_from_prompt with mocked LLM."""

    def test_raises_when_mock_crew_disabled(self):
        """Raises when MOCK_CREW_ENABLED is false."""
        with patch(
            "claim_agent.mock_crew.claim_generator.get_mock_crew_config",
            return_value={"enabled": False, "seed": None},
        ):
            with pytest.raises(ValueError, match="Mock Crew must be enabled"):
                generate_claim_from_prompt("parking lot fender bender")

    def test_generates_claim_with_mocked_llm(self):
        """Produces valid ClaimInput when LLM returns valid JSON."""
        mock_db = {
            "policies": {
                "POL-X": {"status": "active", "coverages": ["collision"]},
            },
            "policy_vehicles": {
                "POL-X": [
                    {
                        "vin": "1HGBH41JXMN109186",
                        "vehicle_year": 2021,
                        "vehicle_make": "Honda",
                        "vehicle_model": "Accord",
                    },
                ],
            },
        }
        llm_response = type("R", (), {"choices": [type("C", (), {
            "message": type("M", (), {
                "content": '{"incident_date": "2025-01-15", "incident_description": "Rear-ended at stoplight.", '
                '"damage_description": "Rear bumper dented.", "estimated_damage": 2500}'
            })()
        })()]})()
        with patch(
            "claim_agent.mock_crew.claim_generator.get_mock_crew_config",
            return_value={"enabled": True, "seed": 123},
        ):
            with patch(
                "claim_agent.mock_crew.claim_generator.load_mock_db",
                return_value=mock_db,
            ):
                with patch(
                    "claim_agent.mock_crew.claim_generator.litellm.completion",
                    return_value=llm_response,
                ):
                    with patch(
                        "claim_agent.mock_crew.claim_generator.get_llm",
                    ):
                        result = generate_claim_from_prompt("parking lot fender bender")
        assert result.policy_number == "POL-X"
        assert result.vin == "1HGBH41JXMN109186"
        assert result.vehicle_make == "Honda"
        assert str(result.incident_date) == "2025-01-15"
        assert result.damage_description == "Rear bumper dented."
        assert result.estimated_damage == 2500

    def test_raises_when_llm_returns_invalid_json(self):
        """Raises when LLM does not return valid JSON."""
        mock_db = {
            "policies": {"POL-X": {"status": "active", "coverages": ["collision"]}},
            "policy_vehicles": {
                "POL-X": [
                    {"vin": "V1", "vehicle_year": 2020, "vehicle_make": "Honda", "vehicle_model": "Civic"},
                ],
            },
        }
        llm_response = type("R", (), {"choices": [type("C", (), {
            "message": type("M", (), {"content": "I cannot generate that."})()
        })()]})()
        with patch(
            "claim_agent.mock_crew.claim_generator.get_mock_crew_config",
            return_value={"enabled": True, "seed": None},
        ):
            with patch(
                "claim_agent.mock_crew.claim_generator.load_mock_db",
                return_value=mock_db,
            ):
                with patch(
                    "claim_agent.mock_crew.claim_generator.litellm.completion",
                    return_value=llm_response,
                ):
                    with patch(
                        "claim_agent.mock_crew.claim_generator.get_llm",
                    ):
                        with pytest.raises(ValueError, match="LLM did not return valid JSON"):
                            generate_claim_from_prompt("some prompt")


class TestGenerateIncidentDamageFromVehicle:
    """Tests for generate_incident_damage_from_vehicle with mocked LLM."""

    def test_raises_when_mock_crew_disabled(self):
        """Raises when MOCK_CREW_ENABLED is false."""
        with patch(
            "claim_agent.mock_crew.claim_generator.get_mock_crew_config",
            return_value={"enabled": False, "seed": None},
        ):
            with pytest.raises(ValueError, match="Mock Crew must be enabled"):
                generate_incident_damage_from_vehicle(2021, "Honda", "Accord")

    def test_generates_details_with_mocked_llm(self):
        """Produces incident/damage dict when LLM returns valid JSON."""
        llm_response = type("R", (), {"choices": [type("C", (), {
            "message": type("M", (), {
                "content": '{"incident_date": "2025-02-10", "incident_description": "Parking lot fender bender.", '
                '"damage_description": "Front left fender dent.", "estimated_damage": 1800}'
            })()
        })()]})()
        with patch(
            "claim_agent.mock_crew.claim_generator.get_mock_crew_config",
            return_value={"enabled": True, "seed": 42},
        ):
            with patch(
                "claim_agent.mock_crew.claim_generator.litellm.completion",
                return_value=llm_response,
            ):
                with patch(
                    "claim_agent.mock_crew.claim_generator.get_llm",
                ):
                    result = generate_incident_damage_from_vehicle(2021, "Honda", "Accord")
        assert result["incident_date"] == "2025-02-10"
        assert result["incident_description"] == "Parking lot fender bender."
        assert result["damage_description"] == "Front left fender dent."
        assert result["estimated_damage"] == 1800

    def test_raises_when_llm_returns_invalid_json(self):
        """Raises when LLM does not return valid JSON."""
        llm_response = type("R", (), {"choices": [type("C", (), {
            "message": type("M", (), {"content": "I cannot do that."})()
        })()]})()
        with patch(
            "claim_agent.mock_crew.claim_generator.get_mock_crew_config",
            return_value={"enabled": True, "seed": None},
        ):
            with patch(
                "claim_agent.mock_crew.claim_generator.litellm.completion",
                return_value=llm_response,
            ):
                with patch(
                    "claim_agent.mock_crew.claim_generator.get_llm",
                ):
                    with pytest.raises(ValueError, match="LLM did not return valid JSON"):
                        generate_incident_damage_from_vehicle(2020, "Toyota", "Camry")

    def test_uses_custom_prompt_when_provided(self):
        """Custom prompt is passed to LLM."""
        llm_response = type("R", (), {"choices": [type("C", (), {
            "message": type("M", (), {
                "content": '{"incident_date": "2025-01-01", "incident_description": "Flood damage.", '
                '"damage_description": "Water damage to interior.", "estimated_damage": null}'
            })()
        })()]})()
        with patch(
            "claim_agent.mock_crew.claim_generator.get_mock_crew_config",
            return_value={"enabled": True, "seed": None},
        ):
            with patch(
                "claim_agent.mock_crew.claim_generator.litellm.completion",
                return_value=llm_response,
            ) as mock_completion:
                with patch(
                    "claim_agent.mock_crew.claim_generator.get_llm",
                ):
                    result = generate_incident_damage_from_vehicle(
                        2022, "Tesla", "Model 3", prompt="flood damage"
                    )
        assert "flood" in mock_completion.call_args[1]["messages"][0]["content"].lower()
        assert result["estimated_damage"] is None
