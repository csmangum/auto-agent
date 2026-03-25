"""Unit tests for LLM configuration."""

import os
import threading
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.config import reload_settings


class TestLLMConfig:
    """Tests for config/llm.py."""

    def test_get_llm_no_api_key_raises(self):
        """Test get_llm raises ValueError when OPENAI_API_KEY is not set."""
        from claim_agent.config.llm import get_llm

        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        original_openrouter = os.environ.get("OPENROUTER_API_KEY")
        try:
            os.environ["OPENAI_API_KEY"] = ""
            os.environ["OPENAI_API_BASE"] = ""
            if "OPENROUTER_API_KEY" in os.environ:
                del os.environ["OPENROUTER_API_KEY"]
            reload_settings()

            with pytest.raises(ValueError, match="OPENAI_API_KEY"):
                get_llm()
        finally:
            if original_key is not None:
                os.environ["OPENAI_API_KEY"] = original_key
            elif "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            if original_base is not None:
                os.environ["OPENAI_API_BASE"] = original_base
            elif "OPENAI_API_BASE" in os.environ:
                del os.environ["OPENAI_API_BASE"]
            if original_openrouter is not None:
                os.environ["OPENROUTER_API_KEY"] = original_openrouter
            elif "OPENROUTER_API_KEY" in os.environ:
                del os.environ["OPENROUTER_API_KEY"]
            reload_settings()

    def test_get_llm_with_api_key(self):
        """Test get_llm returns LLM when API key is set."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        original_model = os.environ.get("OPENAI_MODEL_NAME")
        
        try:
            os.environ["OPENAI_API_KEY"] = "test-api-key"
            os.environ["OPENAI_API_BASE"] = ""
            os.environ["OPENAI_MODEL_NAME"] = ""
            reload_settings()
            
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                result = get_llm()
                mock_llm.assert_called_once_with(
                    model="gpt-4o-mini", api_key="test-api-key", timeout=120
                )
                assert result is not None
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
            reload_settings()

    def test_get_llm_with_custom_model(self):
        """Test get_llm uses custom model name from env."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_model = os.environ.get("OPENAI_MODEL_NAME")
        original_base = os.environ.get("OPENAI_API_BASE")
        
        try:
            os.environ["OPENAI_API_KEY"] = "test-api-key"
            os.environ["OPENAI_MODEL_NAME"] = "gpt-4-turbo"
            os.environ["OPENAI_API_BASE"] = ""
            reload_settings()
            
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                mock_llm.assert_called_once_with(
                    model="gpt-4-turbo", api_key="test-api-key", timeout=120
                )
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
            elif "OPENAI_API_BASE" in os.environ:
                del os.environ["OPENAI_API_BASE"]
            reload_settings()

    def test_get_llm_with_openrouter(self):
        """Test get_llm configures OpenRouter when base URL is set."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        original_model = os.environ.get("OPENAI_MODEL_NAME")
        
        try:
            os.environ["OPENAI_API_KEY"] = "test-api-key"
            os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
            os.environ["OPENAI_MODEL_NAME"] = "anthropic/claude-3"
            reload_settings()
            
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                mock_llm.assert_called_once_with(
                    model="anthropic/claude-3",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="test-api-key",
                    timeout=120,
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
            reload_settings()

    def test_setup_observability_thread_safe(self):
        """Concurrent setup_observability() runs LangSmith setup only once."""
        import claim_agent.config.llm as llm_module

        setup_count = 0
        count_lock = threading.Lock()

        def mock_setup():
            nonlocal setup_count
            with count_lock:
                setup_count += 1
            return False

        with patch.object(llm_module, "_langsmith_initialized", False):
            with patch(
                "claim_agent.observability.tracing.setup_langsmith",
                side_effect=mock_setup,
            ):
                threads = [
                    threading.Thread(target=llm_module.setup_observability)
                    for _ in range(10)
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()

                assert setup_count == 1

    def test_get_llm_placeholder_key_raises(self):
        """Test get_llm raises when OPENAI_API_KEY is a placeholder from .env.example."""
        from claim_agent.config.llm import get_llm

        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        original_openrouter = os.environ.get("OPENROUTER_API_KEY")
        try:
            os.environ["OPENAI_API_KEY"] = "your_openrouter_key"
            os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
            if "OPENROUTER_API_KEY" in os.environ:
                del os.environ["OPENROUTER_API_KEY"]
            reload_settings()

            with pytest.raises(ValueError, match="placeholder"):
                get_llm()
        finally:
            if original_key is not None:
                os.environ["OPENAI_API_KEY"] = original_key
            elif "OPENAI_API_KEY" in os.environ:
                del os.environ["OPENAI_API_KEY"]
            if original_base is not None:
                os.environ["OPENAI_API_BASE"] = original_base
            elif "OPENAI_API_BASE" in os.environ:
                del os.environ["OPENAI_API_BASE"]
            if original_openrouter is not None:
                os.environ["OPENROUTER_API_KEY"] = original_openrouter
            elif "OPENROUTER_API_KEY" in os.environ:
                del os.environ["OPENROUTER_API_KEY"]
            reload_settings()

    def test_get_llm_openrouter_fallback_when_placeholder(self):
        """Test get_llm uses OPENROUTER_API_KEY when OPENAI_API_KEY is placeholder."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        original_model = os.environ.get("OPENAI_MODEL_NAME")
        original_openrouter = os.environ.get("OPENROUTER_API_KEY")
        try:
            os.environ["OPENAI_API_KEY"] = "your_openrouter_key"
            os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
            os.environ["OPENAI_MODEL_NAME"] = ""
            os.environ["OPENROUTER_API_KEY"] = "sk-real-openrouter-key"
            reload_settings()

            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                mock_llm.assert_called_once_with(
                    model="gpt-4o-mini",
                    base_url="https://openrouter.ai/api/v1",
                    api_key="sk-real-openrouter-key",
                    timeout=120,
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
            if original_openrouter is not None:
                os.environ["OPENROUTER_API_KEY"] = original_openrouter
            elif "OPENROUTER_API_KEY" in os.environ:
                del os.environ["OPENROUTER_API_KEY"]
            if original_model is not None:
                os.environ["OPENAI_MODEL_NAME"] = original_model
            elif "OPENAI_MODEL_NAME" in os.environ:
                del os.environ["OPENAI_MODEL_NAME"]
            reload_settings()

    def test_get_llm_returns_llm_object(self):
        """Test that get_llm returns an LLM object with valid API key."""
        original_key = os.environ.get("OPENAI_API_KEY")
        original_base = os.environ.get("OPENAI_API_BASE")
        
        try:
            os.environ["OPENAI_API_KEY"] = "sk-test-key-12345"
            if "OPENAI_API_BASE" in os.environ:
                del os.environ["OPENAI_API_BASE"]
            reload_settings()
            
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
            reload_settings()


class TestPromptCacheConfig:
    """Tests for LLMConfig prompt-cache fields and get_llm() cache kwargs."""

    # -----------------------------------------------------------------
    # helpers
    # -----------------------------------------------------------------

    def _set_env(self, **kwargs):
        """Set env vars and return the originals for cleanup."""
        originals = {}
        for k, v in kwargs.items():
            originals[k] = os.environ.get(k)
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        return originals

    def _restore_env(self, originals):
        for k, v in originals.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # -----------------------------------------------------------------
    # LLMConfig field defaults
    # -----------------------------------------------------------------

    def test_cache_disabled_by_default(self):
        """LLM_CACHE_ENABLED should default to False."""
        originals = self._set_env(
            LLM_CACHE_ENABLED=None,
            LLM_CACHE_SEED=None,
            LLM_ANTHROPIC_PROMPT_CACHE=None,
        )
        try:
            reload_settings()
            from claim_agent.config import get_settings
            cfg = get_settings().llm
            assert cfg.cache_enabled is False
            assert cfg.cache_seed is None
            assert cfg.anthropic_prompt_cache is False
        finally:
            self._restore_env(originals)
            reload_settings()

    def test_cache_enabled_env_var(self):
        """LLM_CACHE_ENABLED=true sets cache_enabled to True."""
        originals = self._set_env(LLM_CACHE_ENABLED="true", LLM_CACHE_SEED=None)
        try:
            reload_settings()
            from claim_agent.config import get_settings
            assert get_settings().llm.cache_enabled is True
        finally:
            self._restore_env(originals)
            reload_settings()

    def test_cache_seed_env_var(self):
        """LLM_CACHE_SEED sets cache_seed to the given integer."""
        originals = self._set_env(LLM_CACHE_ENABLED="true", LLM_CACHE_SEED="99")
        try:
            reload_settings()
            from claim_agent.config import get_settings
            assert get_settings().llm.cache_seed == 99
        finally:
            self._restore_env(originals)
            reload_settings()

    def test_anthropic_prompt_cache_env_var(self):
        """LLM_ANTHROPIC_PROMPT_CACHE=true sets anthropic_prompt_cache to True."""
        originals = self._set_env(LLM_ANTHROPIC_PROMPT_CACHE="true")
        try:
            reload_settings()
            from claim_agent.config import get_settings
            assert get_settings().llm.anthropic_prompt_cache is True
        finally:
            self._restore_env(originals)
            reload_settings()

    # -----------------------------------------------------------------
    # get_llm() kwargs forwarding
    # -----------------------------------------------------------------

    def test_get_llm_no_cache_kwargs_by_default(self):
        """get_llm() should NOT pass caching/extra_headers when cache is off."""
        originals = self._set_env(
            OPENAI_API_KEY="sk-test-default",
            OPENAI_API_BASE=None,
            LLM_CACHE_ENABLED="false",
            LLM_CACHE_SEED=None,
            LLM_ANTHROPIC_PROMPT_CACHE="false",
        )
        try:
            reload_settings()
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                _, kwargs = mock_llm.call_args
                assert "caching" not in kwargs
                assert "cache_seed" not in kwargs
                assert "extra_headers" not in kwargs
        finally:
            self._restore_env(originals)
            reload_settings()

    def test_get_llm_passes_caching_true(self):
        """get_llm() passes caching=True when LLM_CACHE_ENABLED=true."""
        originals = self._set_env(
            OPENAI_API_KEY="sk-test-cache",
            OPENAI_API_BASE=None,
            LLM_CACHE_ENABLED="true",
            LLM_CACHE_SEED=None,
            LLM_ANTHROPIC_PROMPT_CACHE="false",
        )
        try:
            reload_settings()
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                _, kwargs = mock_llm.call_args
                assert kwargs.get("caching") is True
                assert "cache_seed" not in kwargs
        finally:
            self._restore_env(originals)
            reload_settings()

    def test_get_llm_passes_cache_seed(self):
        """get_llm() passes cache_seed when LLM_CACHE_SEED is set."""
        originals = self._set_env(
            OPENAI_API_KEY="sk-test-seed",
            OPENAI_API_BASE=None,
            LLM_CACHE_ENABLED="true",
            LLM_CACHE_SEED="42",
            LLM_ANTHROPIC_PROMPT_CACHE="false",
        )
        try:
            reload_settings()
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                _, kwargs = mock_llm.call_args
                assert kwargs.get("caching") is True
                assert kwargs.get("cache_seed") == 42
        finally:
            self._restore_env(originals)
            reload_settings()

    def test_get_llm_passes_anthropic_beta_header(self):
        """get_llm() adds anthropic-beta header when LLM_ANTHROPIC_PROMPT_CACHE=true."""
        originals = self._set_env(
            OPENAI_API_KEY="sk-test-anthropic",
            OPENAI_API_BASE=None,
            LLM_CACHE_ENABLED="false",
            LLM_CACHE_SEED=None,
            LLM_ANTHROPIC_PROMPT_CACHE="true",
        )
        try:
            reload_settings()
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                _, kwargs = mock_llm.call_args
                headers = kwargs.get("extra_headers", {})
                assert headers.get("anthropic-beta") == "prompt-caching-2024-07-31"
        finally:
            self._restore_env(originals)
            reload_settings()

    def test_get_llm_combined_cache_and_anthropic(self):
        """get_llm() correctly merges caching and Anthropic beta header when both are on."""
        originals = self._set_env(
            OPENAI_API_KEY="sk-combined",
            OPENAI_API_BASE=None,
            LLM_CACHE_ENABLED="true",
            LLM_CACHE_SEED="7",
            LLM_ANTHROPIC_PROMPT_CACHE="true",
        )
        try:
            reload_settings()
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                _, kwargs = mock_llm.call_args
                assert kwargs.get("caching") is True
                assert kwargs.get("cache_seed") == 7
                assert kwargs["extra_headers"]["anthropic-beta"] == "prompt-caching-2024-07-31"
        finally:
            self._restore_env(originals)
            reload_settings()

    def test_get_llm_openrouter_with_cache(self):
        """get_llm() passes cache kwargs and anthropic header through OpenRouter path."""
        originals = self._set_env(
            OPENAI_API_KEY="sk-openrouter",
            OPENAI_API_BASE="https://openrouter.ai/api/v1",
            OPENAI_MODEL_NAME="anthropic/claude-3-sonnet",
            LLM_CACHE_ENABLED="true",
            LLM_CACHE_SEED=None,
            LLM_ANTHROPIC_PROMPT_CACHE="true",
        )
        try:
            reload_settings()
            with patch("crewai.LLM") as mock_llm:
                mock_llm.return_value = MagicMock()
                from claim_agent.config.llm import get_llm
                get_llm()
                _, kwargs = mock_llm.call_args
                assert kwargs.get("caching") is True
                assert kwargs["extra_headers"]["anthropic-beta"] == "prompt-caching-2024-07-31"
                assert kwargs.get("base_url") == "https://openrouter.ai/api/v1"
        finally:
            self._restore_env(originals)
            reload_settings()

