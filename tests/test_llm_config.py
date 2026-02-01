"""Unit tests for LLM configuration."""

import os
from unittest.mock import patch, MagicMock

import pytest


class TestLLMConfig:
    """Tests for config/llm.py."""

    def test_get_llm_no_api_key_raises(self):
        """Test get_llm raises ValueError when OPENAI_API_KEY is not set."""
        from claim_agent.config.llm import get_llm

        # Save original value
        original_key = os.environ.get("OPENAI_API_KEY")
        try:
            # Clear the API key
            if "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            
            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                get_llm()
        finally:
            # Restore original value
            if original_key is not None:
                os.environ["OPENAI_API_KEY"] = original_key

    def test_get_llm_with_api_key(self):
        """Test get_llm returns LLM when API key is set."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        original_model = os.environ.get("OPENAI_MODEL_NAME")
        
        try:
            os.environ["OPENAI_API_KEY"] = "test-api-key"
            if "OPENAI_API_BASE" in os.environ:
                del os.environ["OPENAI_API_BASE"]
            if "OPENAI_MODEL_NAME" in os.environ:
                del os.environ["OPENAI_MODEL_NAME"]
            
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                result = get_llm()
                mock_llm.assert_called_once_with(model="gpt-4o-mini", api_key="test-api-key")
                assert result is not None
        finally:
            # Restore original values
            if original_key is not None:
                os.environ["OPENAI_API_KEY"] = original_key
            elif "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            if original_base is not None:
                os.environ["OPENAI_API_BASE"] = original_base
            if original_model is not None:
                os.environ["OPENAI_MODEL_NAME"] = original_model

    def test_get_llm_with_custom_model(self):
        """Test get_llm uses custom model name from env."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_model = os.environ.get("OPENAI_MODEL_NAME")
        original_base = os.environ.get("OPENAI_API_BASE")
        
        try:
            os.environ["OPENAI_API_KEY"] = "test-api-key"
            os.environ["OPENAI_MODEL_NAME"] = "gpt-4-turbo"
            if "OPENAI_API_BASE" in os.environ:
                del os.environ["OPENAI_API_BASE"]
            
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                mock_llm.assert_called_once_with(model="gpt-4-turbo", api_key="test-api-key")
        finally:
            if original_key is not None:
                os.environ["OPENAI_API_KEY"] = original_key
            elif "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            if original_model is not None:
                os.environ["OPENAI_MODEL_NAME"] = original_model
            elif "OPENAI_MODEL_NAME" in os.environ:
                del os.environ["OPENAI_MODEL_NAME"]
            if original_base is not None:
                os.environ["OPENAI_API_BASE"] = original_base

    def test_get_llm_with_openrouter(self):
        """Test get_llm configures OpenRouter when base URL is set."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        original_model = os.environ.get("OPENAI_MODEL_NAME")
        
        try:
            os.environ["OPENAI_API_KEY"] = "test-api-key"
            os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
            os.environ["OPENAI_MODEL_NAME"] = "anthropic/claude-3"
            
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                mock_llm.assert_called_once_with(
                    model="anthropic/claude-3",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test-api-key",
                )
        finally:
            if original_key is not None:
                os.environ["OPENAI_API_KEY"] = original_key
            elif "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            if original_base is not None:
                os.environ["OPENAI_API_BASE"] = original_base
            elif "OPENAI_API_BASE" in os.environ:
                del os.environ["OPENAI_API_BASE"]
            if original_model is not None:
                os.environ["OPENAI_MODEL_NAME"] = original_model
            elif "OPENAI_MODEL_NAME" in os.environ:
                del os.environ["OPENAI_MODEL_NAME"]

    def test_get_llm_returns_llm_object(self):
        """Test that get_llm returns an LLM object with valid API key."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        
        try:
            os.environ["OPENAI_API_KEY"] = "sk-test-key-12345"
            if "OPENAI_API_BASE" in os.environ:
                del os.environ["OPENAI_API_BASE"]
            
            from claim_agent.config.llm import get_llm
            result = get_llm()
            # Should return an LLM object
            assert result is not None
        finally:
            if original_key is not None:
                os.environ["OPENAI_API_KEY"] = original_key
            elif "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            if original_base is not None:
                os.environ["OPENAI_API_BASE"] = original_base
