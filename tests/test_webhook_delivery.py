"""Tests for async webhook delivery: _deliver_one, background event loop, and non-blocking retries."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from unittest.mock import AsyncMock, patch

import httpx

from claim_agent.notifications.webhook import (
    _deliver_one,
    _get_loop,
    _sign_payload,
    dispatch_webhook,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MOCK_CREW_OFF = {"enabled": False, "seed": None}
_MOCK_WEBHOOK_CAPTURE_OFF = {"capture_enabled": False}


def _make_response(status_code: int) -> httpx.Response:
    """Build a minimal httpx.Response stub for mock purposes."""
    request = httpx.Request("POST", "http://example.com/hook")
    return httpx.Response(status_code, request=request)


# ---------------------------------------------------------------------------
# _sign_payload
# ---------------------------------------------------------------------------


class TestSignPayload:
    def test_empty_secret_returns_empty(self):
        assert _sign_payload("", b"data") == ""

    def test_returns_hex_string(self):
        sig = _sign_payload("secret", b"data")
        assert isinstance(sig, str)
        assert len(sig) == 64  # SHA-256 hex digest

    def test_same_inputs_same_output(self):
        assert _sign_payload("key", b"body") == _sign_payload("key", b"body")

    def test_different_secrets_different_output(self):
        assert _sign_payload("key1", b"body") != _sign_payload("key2", b"body")


# ---------------------------------------------------------------------------
# _get_loop – background event loop management
# ---------------------------------------------------------------------------


class TestGetLoop:
    def test_returns_running_event_loop(self):
        loop = _get_loop()
        assert loop.is_running()

    def test_returns_same_loop_on_repeated_calls(self):
        loop1 = _get_loop()
        loop2 = _get_loop()
        assert loop1 is loop2

    def test_loop_runs_in_daemon_thread(self):
        import claim_agent.notifications.webhook as wh_module

        assert wh_module._loop_thread is not None
        assert wh_module._loop_thread.daemon is True
        assert wh_module._loop_thread.is_alive()


# ---------------------------------------------------------------------------
# _deliver_one – async HTTP delivery
# ---------------------------------------------------------------------------


class TestDeliverOneAsync:
    """Unit tests for the async _deliver_one coroutine."""

    def _run(self, coro):
        """Run a coroutine on a fresh event loop (isolated from the shared loop)."""
        return asyncio.run(coro)

    def test_successful_delivery_returns_without_error(self):
        mock_resp = _make_response(200)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            self._run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-1"}, "", 0, None)
            )

        mock_client.post.assert_awaited_once()

    def test_201_response_treated_as_success(self):
        mock_resp = _make_response(201)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            self._run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-2"}, "", 0, None)
            )

        mock_client.post.assert_awaited_once()

    def test_non_retriable_4xx_does_not_retry(self):
        mock_resp = _make_response(400)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            self._run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-3"}, "", 3, None)
            )

        # Only one attempt for non-retriable status code
        assert mock_client.post.await_count == 1

    def test_retriable_500_retries_up_to_max(self):
        mock_resp = _make_response(500)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        # Patch asyncio.sleep so the test doesn't actually sleep
        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "asyncio.sleep", new_callable=AsyncMock
        ):
            self._run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-4"}, "", 2, None)
            )

        # 1 initial + 2 retries = 3 attempts
        assert mock_client.post.await_count == 3

    def test_429_retries_up_to_max(self):
        mock_resp = _make_response(429)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "asyncio.sleep", new_callable=AsyncMock
        ):
            self._run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-5"}, "", 2, None)
            )

        assert mock_client.post.await_count == 3

    def test_connection_error_retries_and_logs(self, caplog):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "asyncio.sleep", new_callable=AsyncMock
        ), caplog.at_level(logging.WARNING, logger="claim_agent.notifications.webhook"):
            self._run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-6"}, "", 1, None)
            )

        assert mock_client.post.await_count == 2
        # Retry attempt logged at WARNING
        assert any(
            "refused" in r.message and r.levelno == logging.WARNING for r in caplog.records
        )
        # Final failure after all retries logged at ERROR
        assert any(r.levelno == logging.ERROR for r in caplog.records)

    def test_success_logs_latency(self, caplog):
        mock_resp = _make_response(200)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), caplog.at_level(
            logging.DEBUG, logger="claim_agent.notifications.webhook"
        ):
            self._run(
                _deliver_one(
                    "http://example.com/hook",
                    {"claim_id": "CLM-7", "event": "claim.submitted"},
                    "",
                    0,
                    None,
                )
            )

        assert any("latency_ms" in r.message for r in caplog.records)

    def test_failure_after_retries_logs_error(self, caplog):
        mock_resp = _make_response(503)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "asyncio.sleep", new_callable=AsyncMock
        ), caplog.at_level(logging.ERROR, logger="claim_agent.notifications.webhook"):
            self._run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-8"}, "", 0, None)
            )

        assert any("failed" in r.message.lower() for r in caplog.records)

    def test_dead_letter_written_on_exhausted_retries(self, tmp_path):
        dead_letter = str(tmp_path / "dead.jsonl")
        mock_resp = _make_response(500)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "asyncio.sleep", new_callable=AsyncMock
        ):
            self._run(
                _deliver_one(
                    "http://example.com/hook",
                    {"claim_id": "CLM-9"},
                    "",
                    0,
                    dead_letter,
                )
            )

        with open(dead_letter) as f:
            line = json.loads(f.read().strip())
        assert line["url"] == "http://example.com/hook"
        assert line["payload"]["claim_id"] == "CLM-9"

    def test_signature_header_added_when_secret_provided(self):
        mock_resp = _make_response(200)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            self._run(
                _deliver_one(
                    "http://example.com/hook", {"claim_id": "CLM-10"}, "mysecret", 0, None
                )
            )

        _, kwargs = mock_client.post.call_args
        assert "X-Webhook-Signature" in kwargs.get("headers", {})

    def test_no_signature_header_when_secret_empty(self):
        mock_resp = _make_response(200)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            self._run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-11"}, "", 0, None)
            )

        _, kwargs = mock_client.post.call_args
        assert "X-Webhook-Signature" not in kwargs.get("headers", {})


# ---------------------------------------------------------------------------
# Non-blocking behaviour: asyncio.sleep vs time.sleep
# ---------------------------------------------------------------------------


class TestNonBlockingRetries:
    """Verify that the background loop runs coroutines concurrently and
    that ``asyncio.sleep`` (not ``time.sleep``) is used for back-off."""

    def test_asyncio_sleep_used_not_time_sleep(self):
        """asyncio.sleep must be called during back-off (not time.sleep, which blocks the loop)."""
        mock_resp = _make_response(500)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_resp)

        async_sleep_calls: list[float] = []

        async def record_sleep(seconds: float) -> None:
            async_sleep_calls.append(seconds)

        with patch("httpx.AsyncClient", return_value=mock_client), patch(
            "claim_agent.notifications.webhook.asyncio.sleep", side_effect=record_sleep
        ):
            asyncio.run(
                _deliver_one("http://example.com/hook", {"claim_id": "CLM-AS"}, "", 2, None)
            )

        # Two retries → two asyncio.sleep calls with exponential back-off
        assert len(async_sleep_calls) == 2
        assert async_sleep_calls[0] == 1  # min(2**0, 60)
        assert async_sleep_calls[1] == 2  # min(2**1, 60)

    def test_multiple_retrying_webhooks_do_not_serially_block(self):
        """Two concurrently-submitted deliveries both complete without one waiting for the other's sleep."""
        results: list[str] = []

        async def fast_deliver():
            await asyncio.sleep(0)  # yield once
            results.append("fast")

        async def slow_deliver():
            await asyncio.sleep(0.05)
            results.append("slow")

        loop = _get_loop()
        f1 = asyncio.run_coroutine_threadsafe(slow_deliver(), loop)
        f2 = asyncio.run_coroutine_threadsafe(fast_deliver(), loop)

        # Both should complete within a generous timeout
        f1.result(timeout=2)
        f2.result(timeout=2)

        # fast_deliver should finish before slow_deliver despite being submitted second
        assert results == ["fast", "slow"]

    def test_dispatch_webhook_does_not_block_caller(self):
        """dispatch_webhook must return immediately, even if the endpoint is slow."""
        with (
            patch(
                "claim_agent.notifications.webhook.get_mock_crew_config",
                return_value=_MOCK_CREW_OFF,
            ),
            patch(
                "claim_agent.notifications.webhook.get_mock_webhook_config",
                return_value=_MOCK_WEBHOOK_CAPTURE_OFF,
            ),
            patch(
                "claim_agent.notifications.webhook.get_webhook_config",
                return_value={
                    "enabled": True,
                    "urls": ["http://example.com/slow"],
                    "secret": "",
                    "max_retries": 0,
                    "dead_letter_path": None,
                },
            ),
            patch("claim_agent.notifications.webhook._deliver_one") as mock_deliver,
        ):
            # Make _deliver_one take a long time (simulate slow endpoint)
            async def slow_coro(*args, **kwargs):
                await asyncio.sleep(0.1)

            mock_deliver.side_effect = slow_coro

            start = time.monotonic()
            dispatch_webhook("claim.submitted", {"claim_id": "CLM-NB"})
            elapsed = time.monotonic() - start

        # dispatch_webhook must return in well under 1 second
        assert elapsed < 1.0
