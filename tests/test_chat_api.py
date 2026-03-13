"""Tests for the chat API endpoint (POST /api/chat)."""

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all chat API tests."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear rate limit buckets before each API test."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets
    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from claim_agent.api.server import app
    return TestClient(app)


def _make_llm_response(content: str = "Hello!", tool_calls=None):
    """Create a mock litellm completion response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls
    message.model_dump.return_value = {
        "role": "assistant",
        "content": content,
        "tool_calls": None,
    }
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _make_tool_call(name: str, arguments: dict, call_id: str = "call_1"):
    """Create a mock tool_call object."""
    fn = MagicMock()
    fn.name = name
    fn.arguments = json.dumps(arguments)
    tc = MagicMock()
    tc.function = fn
    tc.id = call_id
    return tc


def _parse_sse_events(response_text: str) -> list[dict]:
    """Parse SSE response text into a list of event dicts."""
    events = []
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            try:
                events.append(json.loads(line[6:]))
            except json.JSONDecodeError:
                pass
    return events


class TestChatEndpoint:
    def test_returns_sse_text_response(self, client):
        """Basic chat returns SSE with text and done events."""
        mock_resp = _make_llm_response("I can help you with claims!")
        with patch("claim_agent.chat.agent.litellm.completion", return_value=mock_resp):
            resp = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "Hello"}]},
            )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]
        events = _parse_sse_events(resp.text)
        types = [e["type"] for e in events]
        assert "text" in types
        assert "done" in types
        text_events = [e for e in events if e["type"] == "text"]
        assert text_events[0]["content"] == "I can help you with claims!"

    def test_with_tool_call(self, client):
        """Chat with tool call: LLM calls tool, gets result, then responds."""
        # First call: LLM returns a tool call
        tool_call = _make_tool_call("get_claims_stats", {})
        tool_response = _make_llm_response(content=None, tool_calls=[tool_call])
        tool_response.choices[0].message.content = None
        tool_msg_dump = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_claims_stats", "arguments": "{}"},
                }
            ],
        }
        tool_response.choices[0].message.model_dump.return_value = tool_msg_dump

        # Second call: LLM returns text
        text_response = _make_llm_response("There are 6 total claims in the system.")

        with patch(
            "claim_agent.chat.agent.litellm.completion",
            side_effect=[tool_response, text_response],
        ):
            resp = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "How many claims?"}]},
            )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        types = [e["type"] for e in events]
        assert "tool_call" in types
        assert "tool_result" in types
        assert "text" in types
        assert "done" in types

        tool_call_event = next(e for e in events if e["type"] == "tool_call")
        assert tool_call_event["name"] == "get_claims_stats"

        tool_result_event = next(e for e in events if e["type"] == "tool_result")
        assert "total_claims" in tool_result_event["result"]

    def test_empty_messages_rejected(self, client):
        """Chat with no messages returns 422."""
        resp = client.post("/api/chat", json={"messages": []})
        assert resp.status_code == 422

    def test_invalid_role_rejected(self, client):
        """Message with invalid role returns 422."""
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "system", "content": "test"}]},
        )
        assert resp.status_code == 422

    def test_empty_content_rejected(self, client):
        """Message with empty content returns 422."""
        resp = client.post(
            "/api/chat",
            json={"messages": [{"role": "user", "content": ""}]},
        )
        assert resp.status_code == 422

    def test_max_tool_rounds(self, client):
        """Ensure the agent stops after max_tool_rounds even if LLM keeps calling tools."""
        # Always return a tool call
        tool_call = _make_tool_call("get_claims_stats", {})
        tool_response = _make_llm_response(content=None, tool_calls=[tool_call])
        tool_response.choices[0].message.content = None
        tool_msg_dump = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_claims_stats", "arguments": "{}"},
                }
            ],
        }
        tool_response.choices[0].message.model_dump.return_value = tool_msg_dump

        with patch(
            "claim_agent.chat.agent.litellm.completion",
            return_value=tool_response,
        ):
            resp = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "test"}]},
            )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        # Should have a done event
        assert any(e["type"] == "done" for e in events)
        # Should have at most 5 tool_call events (max rounds)
        tool_calls = [e for e in events if e["type"] == "tool_call"]
        assert len(tool_calls) <= 5

    def test_llm_error_returns_error_event(self, client):
        """When LLM raises an exception, return an error SSE event."""
        with patch(
            "claim_agent.chat.agent.litellm.completion",
            side_effect=Exception("API unavailable"),
        ):
            resp = client.post(
                "/api/chat",
                json={"messages": [{"role": "user", "content": "test"}]},
            )
        assert resp.status_code == 200  # SSE stream still returns 200
        events = _parse_sse_events(resp.text)
        error_events = [e for e in events if e["type"] == "error"]
        assert len(error_events) == 1
        assert "internal error" in error_events[0]["message"].lower()
        assert any(e["type"] == "done" for e in events)

    def test_multiple_messages_conversation(self, client):
        """Chat with multi-turn conversation history."""
        mock_resp = _make_llm_response("The claim is open.")
        with patch("claim_agent.chat.agent.litellm.completion", return_value=mock_resp):
            resp = client.post(
                "/api/chat",
                json={
                    "messages": [
                        {"role": "user", "content": "What is the status of CLM-TEST001?"},
                        {"role": "assistant", "content": "Let me look that up."},
                        {"role": "user", "content": "Thanks, please check."},
                    ]
                },
            )
        assert resp.status_code == 200
        events = _parse_sse_events(resp.text)
        assert any(e["type"] == "text" for e in events)
