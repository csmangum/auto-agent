"""Webhook delivery with HMAC signing and retry."""

import atexit
import hashlib
import hmac
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

import httpx

from claim_agent.config.settings import get_webhook_config

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webhook")


def _shutdown_executor() -> None:
    """Shut down the webhook executor for clean process exit."""
    _EXECUTOR.shutdown(wait=False)


atexit.register(_shutdown_executor)

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


def _deliver_one(
    url: str,
    payload: dict[str, Any],
    secret: str,
    max_retries: int,
    dead_letter_path: str | None,
) -> None:
    """Deliver webhook to a single URL with retry and exponential backoff."""
    body = json.dumps(payload).encode("utf-8")
    signature = _sign_payload(secret, body)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "claim-agent-webhook/1.0",
    }
    if signature:
        headers["X-Webhook-Signature"] = f"sha256={signature}"

    last_error: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, content=body, headers=headers)
            if 200 <= resp.status_code < 300:
                logger.debug(
                    "Webhook delivered to %s event=%s claim_id=%s",
                    url,
                    payload.get("event"),
                    payload.get("claim_id"),
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
            time.sleep(wait)

    logger.error(
        "Webhook delivery failed after %d attempts to %s: %s",
        max_retries + 1,
        url,
        last_error,
    )
    if dead_letter_path:
        try:
            with open(dead_letter_path, "a") as f:
                f.write(json.dumps({"url": url, "payload": payload, "error": str(last_error)}) + "\n")
        except OSError as e:
            logger.warning("Could not write dead letter to %s: %s", dead_letter_path, e)


def dispatch_webhook(event: str, payload: dict[str, Any]) -> None:
    """Dispatch webhook to all configured URLs. Runs in thread pool, non-blocking."""
    config = get_webhook_config()
    if not config["enabled"] or not config["urls"]:
        return

    payload = {**payload, "event": event, "timestamp": datetime.now(timezone.utc).isoformat()}

    def run():
        for url in config["urls"]:
            try:
                _deliver_one(
                    url,
                    payload,
                    config["secret"],
                    config["max_retries"],
                    config["dead_letter_path"] or None,
                )
            except Exception as e:
                logger.exception("Webhook dispatch error for %s: %s", url, e)

    _EXECUTOR.submit(run)


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
        full_payload = {**payload, "event": "repair.authorized", "timestamp": datetime.now(timezone.utc).isoformat()}
        def run_shop():
            try:
                _deliver_one(
                    shop_url,
                    full_payload,
                    config["secret"],
                    config["max_retries"],
                    config["dead_letter_path"] or None,
                )
            except Exception as e:
                logger.exception("Shop webhook delivery error for %s: %s", shop_url, e)
        _EXECUTOR.submit(run_shop)
