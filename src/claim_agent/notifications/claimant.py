"""Claimant notifications (email/SMS)."""

import logging
from typing import Any

import httpx

from claim_agent.config.settings import get_notification_config

logger = logging.getLogger(__name__)

CLAIMANT_EVENTS = (
    "receipt_acknowledged",
    "denial_letter",
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
    """Send claimant notification for milestone event.

    Args:
        event: One of receipt_acknowledged, denial_letter, estimate_ready, repair_authorized,
            claim_closed, follow_up_request.
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

    subject, message = _build_notification_message(event, claim_id, template_data)

    if email and config["email_enabled"]:
        _send_email(
            api_key=config["sendgrid_api_key"],
            from_email=config["sendgrid_from_email"],
            to_email=email,
            subject=subject,
            message=message,
            event=event,
            claim_id=claim_id,
        )
    if phone and config["sms_enabled"]:
        _send_sms(
            account_sid=config["twilio_account_sid"],
            auth_token=config["twilio_auth_token"],
            from_phone=config["twilio_from_phone"],
            to_phone=phone,
            message=message,
            event=event,
            claim_id=claim_id,
        )


def _build_notification_message(
    event: str, claim_id: str, template_data: dict[str, Any] | None
) -> tuple[str, str]:
    if event == "receipt_acknowledged":
        return (
            f"Claim {claim_id} acknowledgment",
            f"We received and acknowledged your claim {claim_id}.",
        )
    if event == "denial_letter":
        return (
            f"Claim {claim_id} denial letter",
            f"Your claim {claim_id} has been denied. Appeal rights are included in your denial letter.",
        )
    if event == "follow_up_request":
        message = ""
        if template_data and template_data.get("message"):
            message = str(template_data["message"]).strip()
        if message:
            return (f"Claim {claim_id} follow-up", message)
        return (f"Claim {claim_id} follow-up", f"An update is available for your claim {claim_id}.")
    return (f"Claim {claim_id} update", f"An update is available for your claim {claim_id}.")


def _send_email(
    *,
    api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    message: str,
    event: str,
    claim_id: str,
) -> None:
    if not api_key or not from_email:
        logger.warning(
            "Email notifications enabled but provider credentials missing: event=%s claim_id=%s",
            event,
            claim_id,
        )
        return
    payload = {
        "personalizations": [{"to": [{"email": to_email}]}],
        "from": {"email": from_email},
        "subject": subject,
        "content": [{"type": "text/plain", "value": message}],
    }
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if 200 <= response.status_code < 300:
            logger.info("Sent claimant email: event=%s claim_id=%s", event, claim_id)
        else:
            logger.warning(
                "Failed claimant email delivery: event=%s claim_id=%s status=%s",
                event,
                claim_id,
                response.status_code,
            )
    except Exception as e:
        logger.warning(
            "Error sending claimant email: event=%s claim_id=%s error=%s",
            event,
            claim_id,
            e,
        )


def _send_sms(
    *,
    account_sid: str,
    auth_token: str,
    from_phone: str,
    to_phone: str,
    message: str,
    event: str,
    claim_id: str,
) -> None:
    if not account_sid or not auth_token or not from_phone:
        logger.warning(
            "SMS notifications enabled but provider credentials missing: event=%s claim_id=%s",
            event,
            claim_id,
        )
        return
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json",
                data={
                    "From": from_phone,
                    "To": to_phone,
                    "Body": message,
                },
                auth=(account_sid, auth_token),
            )
        if 200 <= response.status_code < 300:
            logger.info("Sent claimant SMS: event=%s claim_id=%s", event, claim_id)
        else:
            logger.warning(
                "Failed claimant SMS delivery: event=%s claim_id=%s status=%s",
                event,
                claim_id,
                response.status_code,
            )
    except Exception as e:
        logger.warning(
            "Error sending claimant SMS: event=%s claim_id=%s error=%s",
            event,
            claim_id,
            e,
        )
