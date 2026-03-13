"""Tests for mock crew image generator."""

import base64
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from claim_agent.mock_crew.image_generator import (
    _build_prompt,
    _extract_base64_from_response,
    _save_image_from_data_url,
    generate_damage_image,
)


class TestBuildPrompt:
    """Tests for _build_prompt."""

    def test_builds_prompt_from_claim_context(self):
        ctx = {
            "vehicle_year": 2020,
            "vehicle_make": "Toyota",
            "vehicle_model": "Camry",
            "damage_description": "rear bumper dent",
            "incident_description": "rear-ended at stoplight",
        }
        prompt = _build_prompt(ctx)
        assert "2020" in prompt
        assert "Toyota" in prompt
        assert "Camry" in prompt
        assert "rear bumper dent" in prompt
        assert "rear-ended at stoplight" in prompt

    def test_uses_defaults_for_missing_keys(self):
        prompt = _build_prompt({})
        assert "vehicle damage" in prompt
        assert "accident" in prompt


class TestExtractBase64FromResponse:
    """Tests for _extract_base64_from_response."""

    def test_extracts_from_message_images(self):
        data_url = "data:image/png;base64,iVBORw0KGgo="
        data = {
            "choices": [
                {
                    "message": {
                        "images": [{"imageUrl": {"url": data_url}}],
                    },
                },
            ],
        }
        assert _extract_base64_from_response(data) == data_url

    def test_extracts_from_message_images_snake_case(self):
        data_url = "data:image/jpeg;base64,/9j/4AAQ="
        data = {
            "choices": [
                {
                    "message": {
                        "images": [{"image_url": {"url": data_url}}],
                    },
                },
            ],
        }
        assert _extract_base64_from_response(data) == data_url

    def test_extracts_from_content_array(self):
        data_url = "data:image/png;base64,abc123"
        data = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "image_url", "image_url": {"url": data_url}},
                        ],
                    },
                },
            ],
        }
        assert _extract_base64_from_response(data) == data_url

    def test_returns_none_when_no_image(self):
        data = {
            "choices": [
                {"message": {"content": [{"type": "text", "text": "No image"}]}},
            ],
        }
        assert _extract_base64_from_response(data) is None

    def test_returns_none_for_empty_choices(self):
        assert _extract_base64_from_response({"choices": []}) is None
        assert _extract_base64_from_response({}) is None


class TestSaveImageFromDataUrl:
    """Tests for _save_image_from_data_url."""

    def test_saves_png_to_path(self, tmp_path):
        raw = b"\x89PNG\r\n\x1a\n"
        b64 = base64.b64encode(raw).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        out = tmp_path / "test.png"
        _save_image_from_data_url(data_url, out)
        assert out.exists()
        assert out.read_bytes() == raw

    def test_raises_for_invalid_data_url(self, tmp_path):
        with pytest.raises(ValueError, match="Invalid data URL"):
            _save_image_from_data_url("not-a-data-url", tmp_path / "x.png")


class TestGenerateDamageImage:
    """Tests for generate_damage_image."""

    def test_raises_when_generator_disabled(self):
        with patch("claim_agent.mock_crew.image_generator.get_settings") as mock_get:
            mock_get.return_value.mock_image.generator_enabled = False
            mock_get.return_value.mock_crew.seed = None
            with pytest.raises(ValueError, match="Mock image generator is disabled"):
                generate_damage_image({"damage_description": "bumper dent"})

    def test_raises_when_api_key_placeholder(self):
        with patch("claim_agent.mock_crew.image_generator.get_settings") as mock_get:
            mock_get.return_value.mock_image.generator_enabled = True
            mock_get.return_value.mock_image.model = "google/gemini-2.0-flash-exp"
            mock_get.return_value.mock_crew.seed = None
            mock_get.return_value.llm.api_key = "your_openrouter_key"
            mock_get.return_value.llm.api_base = "https://openrouter.ai/api/v1"
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": ""}, clear=False):
                with pytest.raises(ValueError, match="OPENAI_API_KEY or OPENROUTER_API_KEY"):
                    generate_damage_image({"damage_description": "bumper dent"})

    def test_success_with_mocked_httpx(self, tmp_path):
        raw = b"\x89PNG\r\n\x1a\n"
        b64 = base64.b64encode(raw).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"

        mock_response = type("Response", (), {})()
        mock_response.status_code = 200
        mock_response.json = lambda: {
            "choices": [
                {"message": {"images": [{"imageUrl": {"url": data_url}}]}},
            ],
        }
        mock_response.raise_for_status = lambda: None

        with patch("claim_agent.mock_crew.image_generator.get_settings") as mock_get:
            mock_get.return_value.mock_image.generator_enabled = True
            mock_get.return_value.mock_image.model = "test-model"
            mock_get.return_value.mock_crew.seed = 42
            mock_get.return_value.paths.attachment_storage_path = str(tmp_path)
            mock_get.return_value.llm.api_key = "sk-real-key"
            mock_get.return_value.llm.api_base = "https://openrouter.ai/api/v1"

            with patch(
                "claim_agent.mock_crew.image_generator.httpx.Client"
            ) as mock_client:
                mock_post = mock_client.return_value.__enter__.return_value.post
                mock_post.return_value = mock_response

                result = generate_damage_image(
                    {
                        "vehicle_year": 2020,
                        "vehicle_make": "Honda",
                        "vehicle_model": "Civic",
                        "damage_description": "front fender",
                        "incident_description": "parking lot",
                    }
                )

        assert result.startswith("file://")
        assert "mock_damage_" in result
        assert result.endswith(".png")
        out_file = Path(result.replace("file://", ""))
        assert out_file.exists()
        assert out_file.read_bytes() == raw

    def test_deterministic_filename_with_seed(self, tmp_path):
        raw = b"\x89PNG\r\n\x1a\n"
        b64 = base64.b64encode(raw).decode("ascii")
        data_url = f"data:image/png;base64,{b64}"
        ctx = {
            "vehicle_year": 2020,
            "vehicle_make": "Honda",
            "damage_description": "bumper",
        }

        mock_response = type("Response", (), {})()
        mock_response.status_code = 200
        mock_response.json = lambda: {
            "choices": [
                {"message": {"images": [{"imageUrl": {"url": data_url}}]}},
            ],
        }
        mock_response.raise_for_status = lambda: None

        def run():
            with patch("claim_agent.mock_crew.image_generator.get_settings") as m:
                m.return_value.mock_image.generator_enabled = True
                m.return_value.mock_image.model = "test"
                m.return_value.mock_crew.seed = 99
                m.return_value.paths.attachment_storage_path = str(tmp_path)
                m.return_value.llm.api_key = "sk-key"
                m.return_value.llm.api_base = "https://openrouter.ai/api/v1"
                with patch(
                    "claim_agent.mock_crew.image_generator.httpx.Client"
                ) as mc:
                    mc.return_value.__enter__.return_value.post.return_value = (
                        mock_response
                    )
                    return generate_damage_image(ctx)

        r1 = run()
        r2 = run()
        assert Path(r1.replace("file://", "")).name == Path(
            r2.replace("file://", "")
        ).name
