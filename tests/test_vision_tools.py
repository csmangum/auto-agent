"""Tests for vision tools and logic."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch


from claim_agent.tools.vision_logic import analyze_damage_photo_impl
from claim_agent.tools.vision_tools import analyze_damage_photo

# Force real vision path (no mock) so tests exercise litellm and file validation
_USE_REAL_VISION = patch(
    "claim_agent.tools.vision_logic._use_mock_vision", return_value=False
)


class TestAnalyzeDamagePhotoImpl:
    """Tests for analyze_damage_photo_impl."""

    def test_data_url_calls_vision_model(self):
        """Data URL is passed to vision model and result is returned."""
        data_url = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="  # minimal valid base64
        mock_resp = type("Resp", (), {"choices": [type("C", (), {"message": type("M", (), {"content": '{"severity":"low","parts_affected":["bumper"],"consistency_with_description":"unknown","notes":"ok"}'})()})()]})()
        with _USE_REAL_VISION, patch("litellm.completion") as mock_completion:
            mock_completion.return_value = mock_resp
            result = analyze_damage_photo_impl(data_url)
        parsed = json.loads(result)
        assert parsed["severity"] == "low"
        assert "bumper" in parsed["parts_affected"]
        mock_completion.assert_called_once()

    def test_file_path_outside_allowed_base_returns_error(self):
        """file:// path outside attachment storage returns error."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"fake")
            path = f.name
        try:
            url = f"file://{path}"
            with _USE_REAL_VISION, patch("claim_agent.tools.vision_logic.get_settings") as mock_get:
                mock_get.return_value.paths.attachment_storage_path = "/allowed/only"
                result = analyze_damage_photo_impl(url)
            parsed = json.loads(result)
            assert parsed["error"] == "Access to this file path is not permitted"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_file_not_found_returns_error(self):
        """file:// path to nonexistent file returns error."""
        url = "file:///nonexistent/path/photo.jpg"
        with _USE_REAL_VISION, patch("claim_agent.tools.vision_logic.get_settings") as mock_get:
            mock_get.return_value.paths.attachment_storage_path = "/nonexistent"
            result = analyze_damage_photo_impl(url)
        parsed = json.loads(result)
        assert parsed["error"] == "File not found"

    def test_file_size_exceeds_limit_returns_error(self):
        """File larger than 20MB returns error."""
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(b"small")
            path = f.name
        try:
            url = f"file://{path}"
            with _USE_REAL_VISION, patch("claim_agent.tools.vision_logic.get_settings") as mock_get:
                mock_get.return_value.paths.attachment_storage_path = str(Path(path).parent)
                with patch("claim_agent.tools.vision_logic.MAX_VISION_FILE_BYTES", 1):
                    result = analyze_damage_photo_impl(url)
            parsed = json.loads(result)
            assert "exceeds the limit" in parsed["error"]
        finally:
            Path(path).unlink(missing_ok=True)

    def test_vision_model_exception_returns_error_in_result(self):
        """When litellm raises, error is captured in result."""
        with _USE_REAL_VISION, patch("litellm.completion") as mock_completion:
            mock_completion.side_effect = Exception("API error")
            result = analyze_damage_photo_impl("data:image/jpeg;base64,abc")
        parsed = json.loads(result)
        assert parsed["error"] == "API error"

    def test_includes_damage_description_in_prompt(self):
        """damage_description is included in the prompt when provided."""
        with _USE_REAL_VISION, patch("litellm.completion") as mock_completion:
            mock_completion.return_value = type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": '{"severity":"low","parts_affected":[],"consistency_with_description":"consistent","notes":""}'})()})()]})()
            analyze_damage_photo_impl("data:image/jpeg;base64,x", damage_description="bumper damage")
        call_kwargs = mock_completion.call_args[1]
        messages = call_kwargs["messages"]
        assert "bumper damage" in messages[0]["content"][0]["text"]


class TestAnalyzeDamagePhotoTool:
    """Tests for the CrewAI analyze_damage_photo tool."""

    def test_tool_delegates_to_impl(self):
        """Tool delegates to analyze_damage_photo_impl."""
        with patch("claim_agent.tools.vision_tools.analyze_damage_photo_impl") as mock_impl:
            mock_impl.return_value = '{"severity":"low","parts_affected":[],"consistency_with_description":"unknown","notes":""}'
            result = analyze_damage_photo.run(image_url="data:image/jpeg;base64,x")
            mock_impl.assert_called_once_with("data:image/jpeg;base64,x", None)
            assert "severity" in result
