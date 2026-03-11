"""Claimant notifications (email/SMS). Stub implementation.

When NOTIFICATION_EMAIL_ENABLED or NOTIFICATION_SMS_ENABLED is true and
claimant contact info is present, logs intent. Real SendGrid/Twilio
integration would be implemented via an adapter.
"""

import logging
from typing import Any

from claim_agent.config.settings import get_notification_config

logger = logging.getLogger(__name__)

CLAIMANT_EVENTS = (
    "receipt_acknowledged",
    "estimate_ready",
    "repair_authorized",
    "claim_closed",
    "follow_up_request",
)


def notify_claimant(
    event: str,
    claim_id: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    opt_out: bool = False,
    template_data: dict[str, Any] | None = None,
) -> None:
    """Send claimant notification for milestone event. Stub: logs intent when contact present.

    Args:
        event: One of receipt_acknowledged, estimate_ready, repair_authorized, claim_closed.
        claim_id: Claim ID.
        email: Optional claimant email.
        phone: Optional claimant phone for SMS.
        opt_out: If True, skip notification.
        template_data: Optional template variables.
    """
    if opt_out:
        return
    if not email and not phone:
        return

    config = get_notification_config()
    if not config["email_enabled"] and not config["sms_enabled"]:
        return

    if event not in CLAIMANT_EVENTS:
        logger.warning("Unknown claimant event: %s", event)
        return

    if email and config["email_enabled"]:
        logger.info(
            "Would send claimant email: event=%s claim_id=%s (stub; integrate SendGrid adapter)",
            event,
            claim_id,
        )
    if phone and config["sms_enabled"]:
        logger.info(
            "Would send claimant SMS: event=%s claim_id=%s (stub; integrate Twilio adapter)",
            event,
            claim_id,
        )
