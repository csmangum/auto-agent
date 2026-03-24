"""Mock Repair Shop: intercept repair-shop follow-up notifications during testing.

When ``MOCK_CREW_ENABLED=true`` and ``MOCK_REPAIR_SHOP_ENABLED=true``, calls to
:func:`claim_agent.notifications.user.notify_user` for ``user_type=repair_shop``
are intercepted before any real portal or API integration is attempted.  The mock:

1. Logs the notification metadata (claim_id, message length, identifier) at INFO
   level—the raw message body is emitted only at DEBUG to avoid leaking PII.
2. Queues a configurable acknowledgment response (``MOCK_REPAIR_SHOP_RESPONSE_TEMPLATE``)
   under the claim_id so tests can drain it with
   :func:`get_pending_repair_shop_responses` and assert on shop acknowledgments.

Thread / process safety:
    An in-process ``threading.Lock`` guards the shared response queue—sufficient
    for pytest-based unit and integration tests that run in a single process.
"""

import logging
import threading
import uuid
from typing import Any

from claim_agent.config.settings import get_mock_repair_shop_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process pending-response queue (claim_id → list of response dicts)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_pending: dict[str, list[dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def mock_notify_repair_shop(
    claim_id: str,
    message: str,
    *,
    identifier: str | None = None,
) -> None:
    """Log a mock repair-shop notification and enqueue a configurable acknowledgment.

    Called by :func:`claim_agent.notifications.user.notify_user` when both
    ``MOCK_CREW_ENABLED`` and ``MOCK_REPAIR_SHOP_ENABLED`` are true and
    ``user_type`` is ``repair_shop``.

    The raw message body is only logged at DEBUG level to avoid leaking PII
    into logs.  INFO carries only non-sensitive metadata (claim_id, identifier,
    message length).

    Args:
        claim_id: Claim identifier.
        message: The message that would have been sent to the repair shop.
        identifier: Optional shop identifier or contact reference.
    """
    logger.info(
        "MockRepairShop: notification suppressed claim_id=%s identifier=%s message_len=%d",
        claim_id,
        identifier,
        len(message),
    )
    logger.debug("MockRepairShop: message body for claim_id=%s: %s", claim_id, message)

    cfg = get_mock_repair_shop_config()
    response_text = cfg["response_template"]
    response_id = str(uuid.uuid4())

    entry: dict[str, Any] = {
        "response_id": response_id,
        "claim_id": claim_id,
        "original_message": message,
        "response_text": response_text,
        "identifier": identifier,
    }

    with _lock:
        _pending.setdefault(claim_id, []).append(entry)

    logger.info(
        "MockRepairShop: acknowledgment queued response_id=%s claim_id=%s",
        response_id,
        claim_id,
    )


def get_pending_repair_shop_responses(claim_id: str) -> list[dict[str, Any]]:
    """Return and clear all pending mock repair-shop responses for *claim_id*.

    Intended for use in tests: call this after triggering a repair-shop
    ``send_user_message`` to drain the acknowledgment queue.

    Args:
        claim_id: The claim whose pending repair-shop responses should be drained.

    Returns:
        List of response dicts, each with keys:
        - ``response_id`` (str): Auto-generated UUID.
        - ``claim_id`` (str): The claim this response belongs to.
        - ``original_message`` (str): The message sent to the repair shop.
        - ``response_text`` (str): The mock acknowledgment text.
        - ``identifier`` (str | None): Optional shop identifier.

        The list is cleared from the queue atomically before returning.
    """
    with _lock:
        return _pending.pop(claim_id, [])


def clear_all_pending_repair_shop_responses() -> None:
    """Clear all queued mock repair-shop responses across all claims.

    Useful in test fixtures to ensure a clean state between test cases.
    """
    with _lock:
        _pending.clear()
