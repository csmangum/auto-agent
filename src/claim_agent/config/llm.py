"""LLM configuration for OpenRouter or default provider."""

import os

from dotenv import load_dotenv

load_dotenv()


def get_llm():
    """Return the configured LLM for agents. Requires OPENAI_API_KEY."""
    try:
        from crewai import LLM
    except ImportError:
        return None
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")
    base = os.environ.get("OPENAI_API_BASE", "").strip()
    model = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini").strip()
    if base and "openrouter" in base.lower():
        return LLM(model=model, base_url=base, api_key=api_key)
    return LLM(model=model, api_key=api_key)
