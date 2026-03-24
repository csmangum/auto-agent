"""Mock Notifier: intercept outbound claimant/user notifications during testing.

When ``MOCK_CREW_ENABLED=true`` and ``MOCK_NOTIFIER_ENABLED=true``, all calls to
:func:`claim_agent.notifications.user.notify_user` are intercepted before any
real email/SMS is attempted.  The mock notifier:

1. Logs the notification (user_type, claim_id, message, template_data keys) at
   INFO level so test output can confirm the message was "sent".
2. Optionally auto-generates a claimant response via the Mock Claimant module
   when ``MOCK_NOTIFIER_AUTO_RESPOND=true`` **and** ``MOCK_CLAIMANT_ENABLED=true``.
   The response is enqueued under ``claim_id`` so tests can drain it with
   :func:`get_pending_mock_responses` and subsequently call
   ``record_user_response``.

Message-ID approach (documented per the plan):
    The notification intercept happens inside ``notify_user``, which does **not**
    receive the database-assigned ``follow_up_message_id``.  Rather than widening
    the notification API (option a) or coupling to the DB (option b), each queued
    response is assigned an auto-generated UUID as its ``response_id``.  Tests that
    need to correlate a response with a specific follow-up message should drain the
    queue immediately after the corresponding ``send_user_message`` call and match
    on ``claim_id``.

Thread / process safety:
    An in-process ``threading.Lock`` guards the shared response queue—sufficient
    for pytest-based unit and integration tests that run in a single process.
"""

import logging
import threading
import uuid
from typing import Any

from claim_agent.config.settings import get_mock_claimant_config, get_mock_notifier_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process pending-response queue (claim_id → list of response dicts)
# ---------------------------------------------------------------------------

_lock: threading.Lock = threading.Lock()
_pending: dict[str, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mock_notify_user(
    user_type: str,
    claim_id: str,
    message: str,
    *,
    template_data: dict[str, Any] | None = None,
) -> None:
    """Log a mock notification and optionally enqueue an auto-generated response.

    Called by :func:`claim_agent.notifications.user.notify_user` when both
    ``MOCK_CREW_ENABLED`` and ``MOCK_NOTIFIER_ENABLED`` are true.

    Args:
        user_type: Recipient type (claimant, repair_shop, adjuster, …).
        claim_id: Claim identifier.
        message: The message that would have been sent.
        template_data: Optional template variables included with the message.
    """
    td_keys = list(template_data.keys()) if template_data else []
    logger.info(
        "MockNotifier: notification suppressed for user_type=%s claim_id=%s "
        "template_data_keys=%s | message=%s",
        user_type,
        claim_id,
        td_keys,
        message,
    )

    # Auto-respond only when the mock claimant is also enabled
    notifier_cfg = get_mock_notifier_config()
    if not notifier_cfg.get("auto_respond"):
        return

    claimant_cfg = get_mock_claimant_config()
    if not claimant_cfg.get("enabled"):
        logger.debug(
            "MockNotifier: auto_respond requested but MOCK_CLAIMANT_ENABLED is false; "
            "skipping for claim_id=%s",
            claim_id,
        )
        return

    from claim_agent.mock_crew.claimant import respond_to_message

    response_text = respond_to_message(claim_id, message, claim_context=None)
    response_id = str(uuid.uuid4())

    entry: dict[str, Any] = {
        "response_id": response_id,
        "claim_id": claim_id,
        "original_message": message,
        "response_text": response_text,
    }

    with _lock:
        _pending.setdefault(claim_id, []).append(entry)

    logger.info(
        "MockNotifier: auto-response queued response_id=%s claim_id=%s",
        response_id,
        claim_id,
    )


def get_pending_mock_responses(claim_id: str) -> list[dict[str, Any]]:
    """Return and clear all pending mock responses for *claim_id*.

    Intended for use in tests: call this after triggering ``send_user_message``
    to drain the response queue and then feed each ``response_text`` into
    ``record_user_response``.

    Args:
        claim_id: The claim whose pending responses should be drained.

    Returns:
        List of response dicts, each with keys:
        - ``response_id`` (str): Auto-generated UUID.
        - ``claim_id`` (str): The claim this response belongs to.
        - ``original_message`` (str): The message the mock claimant replied to.
        - ``response_text`` (str): The mock claimant's reply.

        The list is cleared from the queue atomically before returning.
    """
    with _lock:
        responses = _pending.pop(claim_id, [])
    return responses


def clear_all_pending_mock_responses() -> None:
    """Clear all queued mock responses across all claims.

    Useful in test fixtures to ensure a clean state between test cases.
    """
    with _lock:
        _pending.clear()
