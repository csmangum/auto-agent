"""LLM configuration for OpenRouter or default provider with observability.

This module configures the LLM with:
- LangSmith tracing (if enabled)
- LiteLLM callbacks for token/cost tracking
"""

import os
import logging

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Track whether LangSmith has been set up
_langsmith_initialized = False


def setup_observability() -> None:
    """Set up observability features (LangSmith, callbacks).

    This function should be called once at startup.
    """
    global _langsmith_initialized

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


def get_llm(callbacks: list | None = None):
    """Return the configured LLM for agents. Requires OPENAI_API_KEY.

    Args:
        callbacks: Optional list of callbacks for LiteLLM integration.

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

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")

    base = os.environ.get("OPENAI_API_BASE", "").strip()
    model = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini").strip()

    # Log LLM configuration
    logger.debug(
        "Configuring LLM: model=%s, base_url=%s, callbacks=%s",
        model,
        base if base else "default",
        len(callbacks) if callbacks else 0,
    )

    if base and "openrouter" in base.lower():
        return LLM(model=model, base_url=base, api_key=api_key)
    return LLM(model=model, api_key=api_key)


def get_model_name() -> str:
    """Get the configured model name."""
    return os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini").strip()
