"""Chat API route: streaming conversational endpoint powered by LLM."""

import logging
from typing import Literal

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from claim_agent.api.auth import AuthContext
from claim_agent.api.deps import require_role
from claim_agent.chat.agent import run_chat_agent
from claim_agent.db.database import get_db_path

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])

RequireAdjuster = require_role("adjuster", "supervisor", "admin")


class ChatMessage(BaseModel):
    """A single message in the conversation."""

    role: Literal["user", "assistant"] = Field(
        ..., description="Message role: user or assistant"
    )
    content: str = Field(
        ..., min_length=1, max_length=10000, description="Message content"
    )


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
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    db_path = get_db_path()
    return StreamingResponse(
        run_chat_agent(messages, db_path=db_path),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
