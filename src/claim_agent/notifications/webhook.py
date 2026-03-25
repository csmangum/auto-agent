"""Webhook delivery with HMAC signing and async retry.

Uses a single background asyncio event loop (daemon thread) so that
``asyncio.sleep()`` during exponential-backoff retries never blocks a shared
thread pool.  Multiple in-flight retries run concurrently inside the one loop
without monopolising any thread.
"""

import asyncio
import atexit
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from claim_agent.config.settings import get_mock_crew_config, get_mock_webhook_config, get_webhook_config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Background asyncio event loop
# ---------------------------------------------------------------------------

_loop: asyncio.AbstractEventLoop | None = None
_loop_thread: threading.Thread | None = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return (and lazily start) the shared background event loop."""
    global _loop, _loop_thread
    if _loop is not None and not _loop.is_closed():
        return _loop
    with _loop_lock:
        if _loop is not None and not _loop.is_closed():
            return _loop
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_loop.run_forever,
            name="webhook-event-loop",
            daemon=True,
        )
        _loop_thread.start()
    return _loop


def _shutdown_loop() -> None:
    """Signal the background loop to stop on process exit."""
    global _loop
    if _loop is not None and not _loop.is_closed():
        _loop.call_soon_threadsafe(_loop.stop)


atexit.register(_shutdown_loop)

# UCSPA deadline-approaching event (not status-based)
UCSPA_DEADLINE_APPROACHING = "ucspa.deadline_approaching"

# Map claim status to webhook event name
_STATUS_TO_EVENT: dict[str, str] = {
    "pending": "claim.submitted",
    "processing": "claim.processing",
    "needs_review": "claim.needs_review",
    "failed": "claim.failed",
    "closed": "claim.closed",
    "duplicate": "claim.closed",
    "fraud_suspected": "claim.closed",
    "fraud_confirmed": "claim.closed",
    "settled": "claim.closed",
    "open": "claim.opened",
    "denied": "claim.denied",
    "pending_info": "claim.pending_info",
    "under_investigation": "claim.under_investigation",
    "archived": "claim.archived",
    "purged": "claim.purged",
    "disputed": "claim.disputed",
    "dispute_resolved": "claim.dispute_resolved",
    "partial_loss": "claim.partial_loss",
}


def _sign_payload(secret: str, body: bytes) -> str:
    """Compute HMAC-SHA256 signature of body."""
    if not secret:
        return ""
    return hmac.new(
        secret.encode("utf-8") if isinstance(secret, str) else secret,
        body,
        hashlib.sha256,
    ).hexdigest()


async def _deliver_one(
    url: str,
    payload: dict[str, Any],
    secret: str,
    max_retries: int,
    dead_letter_path: str | None,
) -> None:
    """Deliver webhook to a single URL with async retry and exponential backoff.

    Uses ``httpx.AsyncClient`` so that ``asyncio.sleep()`` during back-off
    yields the event loop to other pending deliveries instead of blocking a
    thread.  Latency and outcome are logged for observability.
    """
    body = json.dumps(payload).encode("utf-8")
    signature = _sign_payload(secret, body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "claim-agent-webhook/1.0",
    }
    if signature:
        headers["X-Webhook-Signature"] = f"sha256={signature}"

    last_error: Exception | None = None
    start = time.monotonic()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for attempt in range(max_retries + 1):
            try:
                resp = await client.post(url, content=body, headers=headers)
                if 200 <= resp.status_code < 300:
                    latency_ms = (time.monotonic() - start) * 1000
                    logger.debug(
                        "Webhook delivered to %s event=%s claim_id=%s attempt=%d latency_ms=%.1f",
                        url,
                        payload.get("event"),
                        payload.get("claim_id"),
                        attempt + 1,
                        latency_ms,
                    )
                    return
                last_error = httpx.HTTPStatusError(
                    f"Webhook returned {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
                # Retriable: 408 (timeout), 429 (rate limit), 5xx
                if resp.status_code in (408, 429) or 500 <= resp.status_code < 600:
                    pass  # fall through to retry
                else:
                    # Non-retriable (typically 4xx). Do not retry.
                    logger.warning(
                        "Non-retriable webhook response %s from %s; not retrying.",
                        resp.status_code,
                        url,
                    )
                    break
            except Exception as e:
                last_error = e
                logger.warning(
                    "Webhook attempt %d/%d to %s failed: %s",
                    attempt + 1,
                    max_retries + 1,
                    url,
                    e,
                )

            if attempt < max_retries:
                wait = min(2**attempt, 60)
                await asyncio.sleep(wait)

    latency_ms = (time.monotonic() - start) * 1000
    logger.error(
        "Webhook delivery failed after %d attempts to %s latency_ms=%.1f: %s",
        max_retries + 1,
        url,
        latency_ms,
        last_error,
    )
    if dead_letter_path:
        line = json.dumps({"url": url, "payload": payload, "error": str(last_error)}) + "\n"

        def _write_dead_letter() -> None:
            with open(dead_letter_path, "a") as f:
                f.write(line)

        try:
            await asyncio.to_thread(_write_dead_letter)
        except OSError as e:
            logger.warning("Could not write dead letter to %s: %s", dead_letter_path, e)


def dispatch_webhook(event: str, payload: dict[str, Any]) -> None:
    """Dispatch webhook to all configured URLs. Non-blocking: schedules delivery on the background event loop."""
    payload = {**payload, "event": event, "timestamp": datetime.now(timezone.utc).isoformat()}

    # Mock webhook capture: record payload in-memory and skip real HTTP delivery
    if get_mock_crew_config()["enabled"] and get_mock_webhook_config()["capture_enabled"]:
        from claim_agent.mock_crew.webhook import capture_webhook

        capture_webhook(event, payload)
        return

    config = get_webhook_config()
    if not config["enabled"] or not config["urls"]:
        return

    async def run():
        for url in config["urls"]:
            try:
                await _deliver_one(
                    url,
                    payload,
                    config["secret"],
                    config["max_retries"],
                    config["dead_letter_path"] or None,
                )
            except Exception as e:
                logger.exception("Webhook dispatch error for %s: %s", url, e)

    asyncio.run_coroutine_threadsafe(run(), _get_loop())


def dispatch_claim_event(
    claim_id: str,
    status: str,
    *,
    summary: str | None = None,
    claim_type: str | None = None,
    payout_amount: float | None = None,
) -> None:
    """Dispatch claim status change webhook. Maps status to event name."""
    event = _STATUS_TO_EVENT.get(status, "claim.closed")
    payload: dict[str, Any] = {
        "claim_id": claim_id,
        "status": status,
    }
    if summary is not None:
        payload["summary"] = summary
    if claim_type is not None:
        payload["claim_type"] = claim_type
    if payout_amount is not None:
        payload["payout_amount"] = payout_amount
    dispatch_webhook(event, payload)


def safe_dispatch_claim_event(
    claim_id: str,
    status: str,
    *,
    summary: str | None = None,
    claim_type: str | None = None,
    payout_amount: float | None = None,
) -> None:
    """Best-effort dispatch of claim event. Logs and swallows errors so notification failures do not affect core operations."""
    try:
        dispatch_claim_event(
            claim_id,
            status,
            summary=summary,
            claim_type=claim_type,
            payout_amount=payout_amount,
        )
    except Exception as e:
        logger.warning("Webhook dispatch failed (best-effort): %s", e)


def dispatch_repair_authorized_from_workflow_output(
    workflow_output: str,
    *,
    log: logging.Logger | logging.LoggerAdapter | None = None,
) -> None:
    """Best-effort dispatch of repair.authorized webhook from workflow output.

    Parses the workflow output for authorization data (authorization_id,
    shop_id, etc.) and fires the webhook if found.
    """
    _log = log or logger
    try:
        data = json.loads(workflow_output)
    except (json.JSONDecodeError, TypeError):
        return
    if not isinstance(data, dict):
        return
    authorization_id = data.get("authorization_id")
    if not authorization_id:
        return
    try:
        dispatch_repair_authorized(
            claim_id=data.get("claim_id") or "",
            shop_id=data.get("shop_id") or "",
            shop_name=data.get("shop_name") or "",
            shop_phone=data.get("shop_phone") or "",
            authorized_amount=float(data.get("authorized_amount") or 0),
            authorization_id=authorization_id,
            shop_webhook_url=data.get("shop_webhook_url"),
        )
    except Exception as e:
        _log.warning("Repair authorization webhook dispatch failed (best-effort): %s", e)


def dispatch_ucspa_deadline_approaching(
    claim_id: str,
    deadline_type: str,
    due_date: str,
    loss_state: str | None = None,
) -> None:
    """Dispatch ucspa.deadline_approaching webhook for claims with deadlines in next N days."""
    payload: dict[str, Any] = {
        "claim_id": claim_id,
        "deadline_type": deadline_type,
        "due_date": due_date,
    }
    if loss_state:
        payload["loss_state"] = loss_state
    dispatch_webhook(UCSPA_DEADLINE_APPROACHING, payload)


def dispatch_repair_authorized(
    claim_id: str,
    shop_id: str,
    shop_name: str,
    shop_phone: str,
    authorized_amount: float,
    authorization_id: str,
    *,
    shop_webhook_url: str | None = None,
) -> None:
    """Dispatch repair.authorized webhook. Also POSTs to shop-specific URL if configured."""
    payload: dict[str, Any] = {
        "claim_id": claim_id,
        "shop_id": shop_id,
        "shop_name": shop_name,
        "shop_phone": shop_phone,
        "authorized_amount": authorized_amount,
        "authorization_id": authorization_id,
    }
    dispatch_webhook("repair.authorized", payload)

    config = get_webhook_config()
    shop_url = shop_webhook_url or config.get("shop_url")
    if shop_url:
        full_payload = {
            **payload,
            "event": "repair.authorized",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        if get_mock_crew_config()["enabled"] and get_mock_webhook_config()["capture_enabled"]:
            from claim_agent.mock_crew.webhook import capture_webhook

            capture_webhook("repair.authorized", full_payload)
            return

        async def run_shop():
            try:
                await _deliver_one(
                    shop_url,
                    full_payload,
                    config["secret"],
                    config["max_retries"],
                    config["dead_letter_path"] or None,
                )
            except Exception as e:
                logger.exception("Shop webhook delivery error for %s: %s", shop_url, e)

        asyncio.run_coroutine_threadsafe(run_shop(), _get_loop())
