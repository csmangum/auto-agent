"""Chat API route: streaming conversational endpoint powered by LLM."""

import json
import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.chat.agent import run_chat_agent
from claim_agent.db.database import get_db_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin")


def _sse_event(data: dict) -> str:
    """Format a dict as an SSE data line."""
    return f"data: {json.dumps(data, default=str)}\n\n"


class ChatMessage(BaseModel):
    """A single message in the conversation."""

    role: Literal["user", "assistant"] = Field(
        ..., description="Message role: user or assistant"
    )
    content: str = Field(
        ...,
        min_length=0,
        max_length=10000,
        description="Message content (empty allowed for assistant in multi-turn)",
    )

    @model_validator(mode="after")
    def user_must_have_content(self) -> "ChatMessage":
        if self.role == "user" and not (self.content or "").strip():
            raise ValueError("User messages must have non-empty content")
        return self


class ChatRequest(BaseModel):
    """Request body for the chat endpoint."""

    messages: list[ChatMessage] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Conversation history (user and assistant messages)",
    )


@router.post("/chat")
async def chat(
    body: ChatRequest,
    auth: AuthContext = RequireAdjuster,
):
    """Streaming chat endpoint.

    Accepts a conversation history and returns an SSE stream with text chunks,
    tool call notifications, and a final done event.

    SSE event format (each line is ``data: <json>\\n\\n``):
    - ``{"type": "text", "content": "..."}`` — streamed text
    - ``{"type": "tool_call", "name": "...", "args": {...}}`` — tool invocation
    - ``{"type": "tool_result", "name": "...", "result": {...}}`` — tool result
    - ``{"type": "done"}`` — turn complete
    - ``{"type": "error", "message": "..."}`` — error
    """
    # Filter out assistant messages with empty content (client may send for continuity)
    messages = [
        {"role": m.role, "content": m.content or ""}
        for m in body.messages
        if m.role == "user" or (m.role == "assistant" and (m.content or "").strip())
    ]
    db_path = get_db_path()

    async def stream_with_error_handling():
        try:
            async for chunk in run_chat_agent(messages, db_path=db_path):
                yield chunk
        except Exception as exc:
            logger.exception("Chat stream error: %s", exc)
            yield _sse_event({"type": "error", "message": "An internal error occurred. Please try again."})
            yield _sse_event({"type": "done"})

    return StreamingResponse(
        stream_with_error_handling(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
