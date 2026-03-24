"""Mock ERP event capture: record outbound ERP pushes in-memory during testing.

When ``MOCK_CREW_ENABLED=true`` and ``MOCK_ERP_CAPTURE_ENABLED=true``, calls to
:func:`capture_erp_event` append the event payload to an in-process list
**instead of** (or in addition to) making real ERP API calls.  Tests can then
call :func:`get_captured_erp_events` to assert on dispatched events.

Usage in tests::

    from claim_agent.mock_crew.erp import (
        clear_captured_erp_events,
        get_captured_erp_events,
        capture_erp_event,
    )

    def test_erp_assignment():
        clear_captured_erp_events()
        # … trigger workflow that calls adapter.push_repair_assignment …
        events = get_captured_erp_events(event_type="assignment")
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


def capture_erp_event(event_type: str, payload: dict[str, Any]) -> None:
    """Append an outbound ERP event payload to the in-memory capture list.

    Called by ERP integration code when mock capture is enabled.

    Args:
        event_type: Short label for the push (``assignment``, ``estimate``,
            ``status``, ``inbound_poll``).
        payload: Full payload dict forwarded to the ERP.
    """
    entry = dict(payload)
    entry["_erp_event_type"] = event_type
    with _lock:
        _captured.append(entry)

    logger.info(
        "MockERP: captured event_type=%s claim_id=%s shop_id=%s",
        event_type,
        payload.get("claim_id"),
        payload.get("shop_id"),
    )


def get_captured_erp_events(event_type: str | None = None) -> list[dict[str, Any]]:
    """Return captured ERP event payloads, optionally filtered by *event_type*.

    Does **not** drain the list—use :func:`clear_captured_erp_events` to reset
    between tests.

    Args:
        event_type: If provided, return only payloads where
            ``payload["_erp_event_type"] == event_type``.

    Returns:
        Snapshot of captured payloads (a new list; modifications do not affect
        the internal store).
    """
    with _lock:
        if event_type is None:
            return [dict(p) for p in _captured]
        return [dict(p) for p in _captured if p.get("_erp_event_type") == event_type]


def clear_captured_erp_events() -> None:
    """Clear all captured ERP event payloads.

    Useful in test fixtures to ensure a clean state between test cases.
    """
    with _lock:
        _captured.clear()
