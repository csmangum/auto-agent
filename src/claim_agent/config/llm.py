"""LLM configuration for OpenRouter or default provider."""

import os

from dotenv import load_dotenv

load_dotenv()


def get_llm():
    """Return the configured LLM for agents. Uses CrewAI's default (reads OPENAI_* env)."""
    try:
        from crewai import LLM
    except ImportError:
        return None
    base = os.environ.get("OPENAI_API_BASE", "").strip()
    model = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini").strip()
    if base and "openrouter" in base.lower():
        return LLM(model=model, base_url=base)
    return LLM(model=model)
