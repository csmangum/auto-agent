"""Chat agent: streaming conversational interface with tool calling.

Uses litellm.completion() with OpenAI-compatible tool schemas.  The agent
can call read-only tools to look up claims, policies, system config, etc.
Responses are streamed as SSE events.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, AsyncGenerator

import litellm

from claim_agent.chat.tools import TOOL_DEFINITIONS, execute_tool
from claim_agent.config.llm import (
    _PLACEHOLDER_KEYS,
    get_model_name,
    setup_observability,
)
from claim_agent.config.settings import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are **Claims Assistant**, an AI helper embedded in an auto insurance claims \
processing system.  You help adjusters, supervisors, and other users understand \
and investigate claims.

**Capabilities (via tools):**
- Look up individual claims by ID
- Search and filter claims by status or type
- View claim audit history (status changes, actions)
- Read claim notes left by agents and crews
- View aggregate statistics (counts by status/type)
- Look up insurance policies and vehicles
- Investigate escalation reasons for claims in needs_review
- View the human review queue
- Explain system configuration (escalation thresholds, fraud settings)

**Guidelines:**
- Be concise and factual.  When reporting claim data, format it clearly.
- Use tools to look up real data instead of guessing.
- When a user asks about a specific claim, use lookup_claim or get_claim_history.
- When a user asks "why was this escalated?", use explain_escalation.
- You can reference the UI: e.g. "You can view this claim at /claims/CLM-XXXXXXXX".
- If you don't know something and no tool can help, say so honestly.
- Format monetary values with $ and commas (e.g. $2,500.00).
- Use markdown for formatting (bold, lists, code blocks) when helpful.
"""

# Maximum number of tool-call rounds per conversation turn to prevent loops.
DEFAULT_MAX_TOOL_ROUNDS = 5
DEFAULT_MAX_MESSAGE_HISTORY = 50


def _get_chat_config() -> dict[str, Any]:
    """Get chat-specific config from settings (if available)."""
    try:
        from claim_agent.config.settings import get_chat_config
        return get_chat_config()
    except (ImportError, AttributeError):
        return {}


def _sse_event(data: dict[str, Any]) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, default=str)}\n\n"


async def run_chat_agent(
    messages: list[dict[str, Any]],
    *,
    db_path: str | None = None,
) -> AsyncGenerator[str, None]:
    """Run the chat agent with tool calling.  Yields SSE-formatted strings.

    SSE event types:
    - ``{"type": "text", "content": "..."}`` – streamed text chunk
    - ``{"type": "tool_call", "name": "...", "args": {...}}`` – tool invocation
    - ``{"type": "tool_result", "name": "...", "result": {...}}`` – tool result
    - ``{"type": "done"}`` – turn complete
    - ``{"type": "error", "message": "..."}`` – error
    """
    setup_observability()
    model = get_model_name()

    # LiteLLM expects OPENROUTER_API_KEY for openrouter/* models; use OPENAI_API_KEY as fallback
    if model.startswith("openrouter/"):
        env_key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if not env_key or env_key in _PLACEHOLDER_KEYS:
            api_key = (get_settings().llm.api_key or "").strip()
            if api_key and api_key not in _PLACEHOLDER_KEYS:
                os.environ["OPENROUTER_API_KEY"] = api_key

    chat_cfg = _get_chat_config()
    max_rounds = chat_cfg.get("max_tool_rounds", DEFAULT_MAX_TOOL_ROUNDS)
    max_history = chat_cfg.get("max_message_history", DEFAULT_MAX_MESSAGE_HISTORY)
    system_prompt = chat_cfg.get("system_prompt_override") or SYSTEM_PROMPT

    # Build message list with system prompt
    llm_messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
    ]
    # Trim to max history (keep most recent)
    trimmed = messages[-max_history:] if len(messages) > max_history else messages
    llm_messages.extend(trimmed)

    try:
        for _round in range(max_rounds):
            # Non-streaming call when we expect tool calls
            response = await _call_llm(model, llm_messages)
            choice = response.choices[0]
            message = choice.message

            # Check for tool calls
            tool_calls = getattr(message, "tool_calls", None)
            if tool_calls:
                # Append assistant message with tool_calls to conversation
                llm_messages.append(message.model_dump())

                for tc in tool_calls:
                    fn_name = tc.function.name
                    try:
                        fn_args = json.loads(tc.function.arguments)
                    except (json.JSONDecodeError, TypeError):
                        fn_args = {}

                    # Notify UI of tool call
                    yield _sse_event({
                        "type": "tool_call",
                        "name": fn_name,
                        "args": fn_args,
                        "id": tc.id,
                    })

                    # Execute tool
                    result_str = execute_tool(fn_name, fn_args, db_path=db_path)

                    # Notify UI of tool result
                    try:
                        result_parsed = json.loads(result_str)
                    except (json.JSONDecodeError, TypeError):
                        result_parsed = result_str
                    yield _sse_event({
                        "type": "tool_result",
                        "name": fn_name,
                        "id": tc.id,
                        "result": result_parsed,
                    })

                    # Add tool result to conversation
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })

                # If this was the last allowed round, stop looping and notify
                if _round + 1 >= max_rounds:
                    logger.warning(
                        "Chat agent reached max tool-call rounds (%d) without a text response.",
                        max_rounds,
                    )
                    yield _sse_event({
                        "type": "error",
                        "message": (
                            "The assistant reached the maximum number of tool-call steps "
                            "without producing a final answer. Please try rephrasing your "
                            "question or breaking it into smaller parts."
                        ),
                    })
                    break

                # Loop back for another LLM call with tool results
                continue

            # No tool calls — stream the text response
            content = getattr(message, "content", None) or ""
            if content:
                yield _sse_event({"type": "text", "content": content})

            # Done with this turn
            break

        yield _sse_event({"type": "done"})

    except Exception:
        logger.exception("Chat agent error")
        yield _sse_event({"type": "error", "message": "An internal error occurred. Please try again."})
        yield _sse_event({"type": "done"})


async def _call_llm(
    model: str,
    messages: list[dict[str, Any]],
) -> Any:
    """Call litellm completion (non-streaming, with tools).

    Runs the blocking litellm call in a thread to avoid blocking the event loop.
    """

    def _sync_call() -> Any:
        return litellm.completion(
            model=model,
            messages=messages,
            tools=TOOL_DEFINITIONS,
            tool_choice="auto",
        )

    return await asyncio.to_thread(_sync_call)
