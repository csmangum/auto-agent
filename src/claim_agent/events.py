"""Claim event emission for decoupled side effects (webhooks, analytics, etc.)."""

import logging
import threading
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)

_listeners: list[Callable[["ClaimEvent"], None]] = []
_listeners_lock = threading.Lock()


@dataclass
class ClaimEvent:
    """Event emitted when claim status or state changes."""

    claim_id: str
    status: str
    summary: str | None = None
    claim_type: str | None = None
    payout_amount: float | None = None


def register_claim_event_listener(callback: Callable[[ClaimEvent], None]) -> None:
    """Register a listener to be invoked when claim events are emitted."""
    with _listeners_lock:
        _listeners.append(callback)


def unregister_claim_event_listener(callback: Callable[[ClaimEvent], None]) -> None:
    """Remove a listener. Used for test cleanup."""
    with _listeners_lock:
        try:
            _listeners.remove(callback)
        except ValueError:
            pass


def emit_claim_event(event: ClaimEvent) -> None:
    """Emit a claim event to all registered listeners."""
    with _listeners_lock:
        listeners = list(_listeners)
    for listener in listeners:
        try:
            listener(event)
        except Exception as e:
            logger.warning(
                "Claim event listener failed (best-effort): %s", e
            )


_webhook_listener_registered = False


def _register_webhook_listener() -> None:
    """Register the default webhook dispatch listener (idempotent)."""
    global _webhook_listener_registered
    if _webhook_listener_registered:
        return

    from claim_agent.notifications.webhook import safe_dispatch_claim_event

    def dispatch(event: ClaimEvent) -> None:
        safe_dispatch_claim_event(
            event.claim_id,
            event.status,
            summary=event.summary,
            claim_type=event.claim_type,
            payout_amount=event.payout_amount,
        )

    register_claim_event_listener(dispatch)
    _webhook_listener_registered = True


_register_webhook_listener()
