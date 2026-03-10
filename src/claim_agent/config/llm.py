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


def get_llm():
    """Return the configured LLM for agents. Requires OPENAI_API_KEY.

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

    model = llm_cfg.model_name.strip() or "gpt-4o-mini"

    # Log LLM configuration
    logger.debug(
        "Configuring LLM: model=%s, base_url=%s",
        model,
        base if base else "default",
    )

    if base and "openrouter" in base.lower():
        # LiteLLM expects OPENROUTER_API_KEY in env when using openrouter/* models
        if not os.environ.get("OPENROUTER_API_KEY"):
            os.environ["OPENROUTER_API_KEY"] = api_key
        return LLM(model=model, base_url=base, api_key=api_key)
    return LLM(model=model, api_key=api_key)


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
