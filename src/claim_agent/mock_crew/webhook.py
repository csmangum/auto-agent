"""Mock Webhook: capture outbound webhook payloads in-memory during testing.

When ``MOCK_CREW_ENABLED=true`` and ``MOCK_WEBHOOK_CAPTURE_ENABLED=true``, calls
to :func:`claim_agent.notifications.webhook.dispatch_webhook` append the payload
to an in-process list **instead of** making real HTTP requests.  Tests can then
call :func:`get_captured_webhooks` to assert on dispatched events.

Usage in tests::

    from claim_agent.mock_crew.webhook import (
        clear_captured_webhooks,
        get_captured_webhooks,
    )

    def test_claim_event_webhook():
        clear_captured_webhooks()
        # … trigger workflow that calls dispatch_webhook …
        events = get_captured_webhooks(event="claim.submitted")
        assert len(events) == 1
        assert events[0]["claim_id"] == "CLM-001"

Thread / process safety:
    An in-process ``threading.Lock`` guards the shared capture list—sufficient
    for pytest-based unit and integration tests that run in a single process.
"""

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process capture store
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_captured: list[dict[str, Any]] = []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def capture_webhook(event: str, payload: dict[str, Any]) -> None:
    """Append a webhook payload to the in-memory capture list.

    Called by :func:`claim_agent.notifications.webhook.dispatch_webhook` when
    both ``MOCK_CREW_ENABLED`` and ``MOCK_WEBHOOK_CAPTURE_ENABLED`` are true.

    Args:
        event: Webhook event name (e.g. ``claim.submitted``).
        payload: Full payload dict (already includes ``event`` and ``timestamp``
            keys added by ``dispatch_webhook``).
    """
    with _lock:
        _captured.append(dict(payload))

    logger.info(
        "MockWebhook: captured event=%s claim_id=%s",
        event,
        payload.get("claim_id"),
    )


def get_captured_webhooks(event: str | None = None) -> list[dict[str, Any]]:
    """Return captured webhook payloads, optionally filtered by event name.

    Does **not** drain the list—use :func:`clear_captured_webhooks` to reset
    between tests.

    Args:
        event: If provided, return only payloads where ``payload["event"] == event``.

    Returns:
        Snapshot of captured payloads (a new list; modifications do not affect
        the internal store).
    """
    with _lock:
        if event is None:
            return list(_captured)
        return [p for p in _captured if p.get("event") == event]


def clear_captured_webhooks() -> None:
    """Clear all captured webhook payloads.

    Useful in test fixtures to ensure a clean state between test cases.
    """
    with _lock:
        _captured.clear()
