"""Tests for mock crew vision analysis."""

import json
import os
from unittest.mock import patch

import pytest

from claim_agent.mock_crew.vision_mock import analyze_damage_photo_mock
from claim_agent.tools.vision_logic import analyze_damage_photo_impl


class TestAnalyzeDamagePhotoMock:
    """Tests for analyze_damage_photo_mock."""

    def test_total_loss_severity(self):
        """Total/totaled/destroyed -> total_loss."""
        for desc in ["car was totaled", "destroyed in fire", "total loss"]:
            result = json.loads(analyze_damage_photo_mock("file://x.jpg", desc, None))
            assert result["severity"] == "total_loss"

    def test_high_severity(self):
        """Severe/extensive -> high."""
        result = json.loads(
            analyze_damage_photo_mock("file://x.jpg", "severe damage to frame", None)
        )
        assert result["severity"] == "high"

    def test_medium_severity(self):
        """Moderate -> medium."""
        result = json.loads(
            analyze_damage_photo_mock("file://x.jpg", "moderate bumper damage", None)
        )
        assert result["severity"] == "medium"

    def test_low_severity_default(self):
        """No severity keywords -> low."""
        result = json.loads(
            analyze_damage_photo_mock("file://x.jpg", "small scratch", None)
        )
        assert result["severity"] == "low"

    def test_parts_affected_from_description(self):
        """Parts extracted from damage description."""
        result = json.loads(
            analyze_damage_photo_mock(
                "file://x.jpg",
                "bumper and fender are dented, door scratched",
                None,
            )
        )
        assert "bumper" in result["parts_affected"]
        assert "fender" in result["parts_affected"]
        assert "door" in result["parts_affected"]

    def test_consistency_when_description_present(self):
        """When description present and parts inferred -> consistent."""
        result = json.loads(
            analyze_damage_photo_mock("file://x.jpg", "bumper damage", None)
        )
        assert result["consistency_with_description"] == "consistent"

    def test_consistency_unknown_when_no_description(self):
        """When no description -> unknown."""
        result = json.loads(analyze_damage_photo_mock("file://x.jpg", None, None))
        assert result["consistency_with_description"] == "unknown"

    def test_uses_claim_context_damage_description(self):
        """Uses claim_context.damage_description when damage_description is None."""
        result = json.loads(
            analyze_damage_photo_mock(
                "file://x.jpg",
                None,
                {"damage_description": "hood and windshield damaged"},
            )
        )
        assert "hood" in result["parts_affected"]
        assert "windshield" in result["parts_affected"]


class TestVisionLogicMockBranch:
    """Tests for vision_logic mock branch."""
    def test_uses_mock_when_vision_adapter_mock(self):
        """When VISION_ADAPTER=mock, uses mock without calling litellm."""
        with patch("claim_agent.tools.vision_logic.get_adapter_backend") as mock_backend:
            mock_backend.return_value = "mock"
            with patch("litellm.completion") as mock_llm:
                result = analyze_damage_photo_impl(
                    "data:image/jpeg;base64,x",
                    damage_description="bumper dent",
                )
                mock_llm.assert_not_called()
        parsed = json.loads(result)
        assert parsed["severity"] == "low"
        assert "bumper" in parsed["parts_affected"]
        assert parsed["error"] is None

    def test_uses_mock_when_mock_crew_enabled_and_claim_context(self):
        """When MOCK_CREW_ENABLED and vision_analysis_source=claim_context, uses mock."""
        with patch("claim_agent.tools.vision_logic.get_adapter_backend") as mock_backend:
            mock_backend.return_value = "real"
            with patch(
                "claim_agent.tools.vision_logic.get_mock_crew_config"
            ) as mock_crew:
                mock_crew.return_value = {"enabled": True, "seed": None}
                with patch(
                    "claim_agent.tools.vision_logic.get_mock_image_config"
                ) as mock_img:
                    mock_img.return_value = {
                        "generator_enabled": False,
                        "model": "",
                        "vision_analysis_source": "claim_context",
                    }
                    with patch("litellm.completion") as mock_llm:
                        result = analyze_damage_photo_impl(
                            "data:image/jpeg;base64,x",
                            damage_description="fender damage",
                        )
                        mock_llm.assert_not_called()
        parsed = json.loads(result)
        assert "fender" in parsed["parts_affected"]

    def test_uses_real_when_vision_adapter_real_and_mock_crew_disabled(self):
        """When VISION_ADAPTER=real and mock crew disabled, calls litellm."""
        with patch("claim_agent.tools.vision_logic.get_adapter_backend") as mock_backend:
            mock_backend.return_value = "real"
            with patch(
                "claim_agent.tools.vision_logic.get_mock_crew_config"
            ) as mock_crew:
                mock_crew.return_value = {"enabled": False, "seed": None}
                with patch("litellm.completion") as mock_llm:
                    mock_llm.return_value = type(
                        "R",
                        (),
                        {
                            "choices": [
                                type(
                                    "C",
                                    (),
                                    {
                                        "message": type(
                                            "M",
                                            (),
                                            {
                                                "content": '{"severity":"low","parts_affected":["bumper"],"consistency_with_description":"consistent","notes":"ok"}'
                                            },
                                        )()
                                    },
                                )()
                            ]
                        },
                    )()
                    result = analyze_damage_photo_impl(
                        "data:image/jpeg;base64,x",
                        damage_description="bumper",
                    )
                    mock_llm.assert_called_once()
        parsed = json.loads(result)
        assert parsed["severity"] == "low"
