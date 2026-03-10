"""Structural typing for LLM instances.

Defines ``LLMProtocol`` -- the minimal interface that all LLM objects
passed through the claim processing pipeline must satisfy.  Using a
Protocol instead of ``Any`` gives IDE autocompletion, catches attribute
typos at type-check time, and documents the expected capabilities.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProtocol(Protocol):
    """Minimal structural contract for an LLM instance.

    ``model`` – the model identifier string (e.g. ``"gpt-4o-mini"``).
    ``get_token_usage_summary()`` – returns an object with
    ``prompt_tokens``, ``completion_tokens``, and ``successful_requests``
    attributes (used by budget enforcement).
    """

    model: str

    def get_token_usage_summary(self) -> object: ...
