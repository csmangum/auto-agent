"""LLM configuration for OpenRouter or default provider with observability.

This module configures the LLM with:
- LangSmith tracing (if enabled)
- LiteLLM callbacks for token/cost tracking
"""

import logging
import os
import threading

from claim_agent.config import get_settings

logger = logging.getLogger(__name__)

# Placeholder API keys from .env.example that cause 401
_PLACEHOLDER_KEYS = frozenset(
    {"", "your_openrouter_key", "your_openai_key", "your-key-here", "your-key"}
)

# Track whether LangSmith has been set up (thread-safe check-and-set)
_langsmith_initialized = False
_langsmith_lock = threading.Lock()

# Thread-local storage for per-call model override (used by fallback chain)
_thread_local = threading.local()


def _get_model_override() -> str | None:
    """Return the thread-local model override, if any."""
    return getattr(_thread_local, "model_override", None)


def _set_model_override(model: str | None) -> None:
    """Set (or clear) the thread-local model override used by get_llm()."""
    _thread_local.model_override = model


def ensure_openrouter_api_key() -> None:
    """Ensure OPENROUTER_API_KEY is set in environment if needed.

    If OPENROUTER_API_KEY is missing or a placeholder, populate it from the
    configured LLM API key. This is needed because litellm expects
    OPENROUTER_API_KEY for openrouter/* models.
    """
    env_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not env_key or env_key in _PLACEHOLDER_KEYS:
        api_key = (get_settings().llm.api_key or "").strip()
        if api_key and api_key not in _PLACEHOLDER_KEYS:
            os.environ["OPENROUTER_API_KEY"] = api_key


def setup_observability() -> None:
    """Set up observability features (LangSmith, callbacks).

    This function should be called once at startup. Thread-safe for
    concurrent claim processing.
    """
    global _langsmith_initialized

    if _langsmith_initialized:
        return

    with _langsmith_lock:
        if _langsmith_initialized:
            return

        try:
            from claim_agent.observability.tracing import setup_langsmith

            if setup_langsmith():
                logger.info("LangSmith tracing enabled")
            else:
                logger.debug("LangSmith tracing not enabled (check LANGSMITH_TRACING env var)")
        except ImportError:
            logger.debug("Observability module not available")

        _langsmith_initialized = True


def get_llm(model_name: str | None = None):
    """Return the configured LLM for agents. Requires OPENAI_API_KEY.

    Args:
        model_name: Override model (for fallback chain). Default uses primary.

    Returns:
        Configured LLM instance.

    Raises:
        ValueError: If OPENAI_API_KEY is not set.
    """
    # Set up observability on first LLM creation
    setup_observability()

    try:
        from crewai import LLM
    except ImportError:
        return None

    llm_cfg = get_settings().llm
    api_key = llm_cfg.api_key.strip()
    base = llm_cfg.api_base.strip()

    # When using OpenRouter, accept OPENROUTER_API_KEY as fallback
    if (not api_key or api_key in _PLACEHOLDER_KEYS) and base and "openrouter" in base.lower():
        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()

    if not api_key or api_key in _PLACEHOLDER_KEYS:
        raise ValueError(
            "OPENAI_API_KEY (or OPENROUTER_API_KEY when using OpenRouter) is required; "
            "replace placeholder values like 'your_openrouter_key' with a real key"
        )

    model = (model_name or _get_model_override() or llm_cfg.model_name or "gpt-4o-mini").strip()

    # Log LLM configuration
    logger.debug(
        "Configuring LLM: model=%s, base_url=%s",
        model,
        base if base else "default",
    )

    if base and "openrouter" in base.lower():
        ensure_openrouter_api_key()
        return LLM(model=model, base_url=base, api_key=api_key)
    return LLM(model=model, api_key=api_key)


def get_llm_fallback_chain() -> list[str]:
    """Return model names for fallback strategy: primary → fallback1 → fallback2 → error."""
    return get_settings().llm.get_fallback_chain()


def get_model_name() -> str:
    """Get the configured model name."""
    return get_settings().llm.model_name.strip() or "gpt-4o-mini"


def has_valid_llm_config() -> bool:
    """Return True if a real LLM API key is configured (same logic as get_llm).

    Use this to skip tests that require a live LLM when only placeholders are set.
    """
    llm_cfg = get_settings().llm
    api_key = llm_cfg.api_key.strip()
    base = llm_cfg.api_base.strip()
    if (not api_key or api_key in _PLACEHOLDER_KEYS) and base and "openrouter" in base.lower():
        api_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
    return bool(api_key) and api_key not in _PLACEHOLDER_KEYS
