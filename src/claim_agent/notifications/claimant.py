"""Claimant notifications (email/SMS)."""

import atexit
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from claim_agent.config.settings import get_mock_crew_config, get_mock_notifier_config, get_notification_config
from claim_agent.mock_crew.notifier import mock_notify_claimant

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="claimant_notify")


def _shutdown_executor() -> None:
    """Shut down the notification executor for clean process exit."""
    _EXECUTOR.shutdown(wait=False)


atexit.register(_shutdown_executor)

CLAIMANT_EVENTS = (
    "receipt_acknowledged",
    "denial_letter",
    "estimate_ready",
    "repair_authorized",
    "claim_closed",
    "follow_up_request",
)

# Events mandated by UCSPA (Unfair Claims Settlement Practices Act).
# Delivery failures for these events are logged at ERROR level and dispatched
# to the failure monitoring webhook (when configured) to ensure regulatory
# compliance tracking.
UCSPA_REQUIRED_EVENTS = (
    "receipt_acknowledged",
    "denial_letter",
    "follow_up_request",
)

HTTP_TIMEOUT_SECONDS = 30.0


def check_notification_readiness() -> dict[str, Any]:
    """Validate that notification provider credentials are configured.

    Returns a summary dict with ``email_ready``, ``sms_ready``, and
    ``warnings`` keys.  Intended for use during startup health checks and
    pilot readiness validation.
    """
    config = get_notification_config()
    warnings: list[str] = []
    email_ready = False
    sms_ready = False

    if config["email_enabled"]:
        if not config["sendgrid_api_key"] or not config["sendgrid_from_email"]:
            warnings.append(
                "NOTIFICATION_EMAIL_ENABLED=true but SENDGRID_API_KEY / "
                "SENDGRID_FROM_EMAIL are not set. Email delivery will fail."
            )
        else:
            email_ready = True
    else:
        warnings.append(
            "Email notifications are disabled (NOTIFICATION_EMAIL_ENABLED=false). "
            "Claimants will not receive UCSPA-required email communications."
        )

    if config["sms_enabled"]:
        if not config["twilio_account_sid"] or not config["twilio_auth_token"] or not config["twilio_from_phone"]:
            warnings.append(
                "NOTIFICATION_SMS_ENABLED=true but TWILIO_ACCOUNT_SID / "
                "TWILIO_AUTH_TOKEN / TWILIO_FROM_PHONE are not set. SMS delivery will fail."
            )
        else:
            sms_ready = True
    else:
        warnings.append(
            "SMS notifications are disabled (NOTIFICATION_SMS_ENABLED=false). "
            "Claimants will not receive UCSPA-required SMS communications."
        )

    for warning in warnings:
        logger.warning("Notification readiness: %s", warning)

    return {"email_ready": email_ready, "sms_ready": sms_ready, "warnings": warnings}


def _report_delivery_failure(
    *,
    channel: str,
    event: str,
    claim_id: str,
    status_code: int | None = None,
    error: str | None = None,
) -> None:
    """Report a delivery failure to the configured monitoring webhook.

    Fires a best-effort POST to ``NOTIFICATION_FAILURE_WEBHOOK_URL`` (when set)
    so that an external alerting system can track bounce/failure rates.  Errors
    during the dispatch are swallowed to avoid masking the original failure.
    """
    config = get_notification_config()
    failure_url = config.get("failure_webhook_url", "")
    if not failure_url:
        return

    import json as _json

    payload: dict[str, Any] = {
        "channel": channel,
        "event": event,
        "claim_id": claim_id,
        "ucspa_required": event in UCSPA_REQUIRED_EVENTS,
    }
    if status_code is not None:
        payload["status_code"] = status_code
    if error is not None:
        payload["error"] = error

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            client.post(
                failure_url,
                content=_json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"},
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to dispatch delivery-failure webhook: %s", exc)


def send_otp_notification(
    claimant_identifier: str,
    channel: str,
    otp: str,
    verification_id: str,
) -> None:
    """Send a DSAR OTP via email or SMS.

    Delivers the OTP code to the claimant using the configured notification
    provider (SendGrid for email, Twilio for SMS).  When the relevant channel
    is not enabled or credentials are missing the delivery is skipped and a
    warning is logged (the token row is still created so the caller can retry).

    Args:
        claimant_identifier: Email address (``channel='email'``) or phone
            number (``channel='sms'``).
        channel: ``'email'`` or ``'sms'``.
        otp: The plaintext OTP code to deliver.
        verification_id: Tracking ID included in the message for debugging.
    """
    # Mock intercept: suppress real OTP delivery during testing
    if get_mock_crew_config()["enabled"] and get_mock_notifier_config()["enabled"]:
        logger.info(
            "MockNotifier: OTP notification suppressed channel=%s verification_id=%s",
            channel,
            verification_id,
        )
        return

    config = get_notification_config()
    subject = "Your DSAR verification code"
    message = (
        f"Your one-time verification code is: {otp}\n\n"
        f"This code expires in {_otp_ttl_minutes()} minutes. "
        "Do not share it with anyone.\n\n"
        f"Reference: {verification_id}"
    )

    if channel == "email":
        if not config["email_enabled"]:
            logger.warning(
                "OTP email not sent: email notifications are disabled. "
                "verification_id=%s",
                verification_id,
            )
            return
        _send_email(
            api_key=config["sendgrid_api_key"],
            from_email=config["sendgrid_from_email"],
            to_email=claimant_identifier,
            subject=subject,
            message=message,
            event="otp_verification",
            claim_id=verification_id,
        )
    elif channel == "sms":
        if not config["sms_enabled"]:
            logger.warning(
                "OTP SMS not sent: SMS notifications are disabled. "
                "verification_id=%s",
                verification_id,
            )
            return
        _send_sms(
            account_sid=config["twilio_account_sid"],
            auth_token=config["twilio_auth_token"],
            from_phone=config["twilio_from_phone"],
            to_phone=claimant_identifier,
            message=f"Your DSAR verification code: {otp}. Expires in {_otp_ttl_minutes()} min.",
            event="otp_verification",
            claim_id=verification_id,
        )
    else:
        logger.warning("send_otp_notification: unknown channel %r", channel)


def _otp_ttl_minutes() -> int:
    """Return the configured OTP TTL in minutes."""
    from claim_agent.config import get_settings

    return get_settings().privacy.otp_ttl_minutes


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

    # Mock intercept: suppress real email/SMS during testing.
    # Must run before contact-info / channel-enabled guards so the mock fires
    # even when email/phone are None or notification channels are disabled.
    if get_mock_crew_config()["enabled"] and get_mock_notifier_config()["enabled"]:
        mock_notify_claimant(event, claim_id)
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
        _email_kwargs = dict(
            api_key=config["sendgrid_api_key"],
            from_email=config["sendgrid_from_email"],
            to_email=email,
            subject=subject,
            message=message,
            event=event,
            claim_id=claim_id,
        )
        _EXECUTOR.submit(_send_email, **_email_kwargs)
    if phone and config["sms_enabled"]:
        _sms_kwargs = dict(
            account_sid=config["twilio_account_sid"],
            auth_token=config["twilio_auth_token"],
            from_phone=config["twilio_from_phone"],
            to_phone=phone,
            message=message,
            event=event,
            claim_id=claim_id,
        )
        _EXECUTOR.submit(_send_sms, **_sms_kwargs)


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
        if template_data:
            raw_message = template_data.get("message")
            if raw_message is not None:
                message = str(raw_message).strip()
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
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
            response = client.post(
                "https://api.sendgrid.com/v3/mail/send",
                json=payload,
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if 200 <= response.status_code < 300:
            logger.info("Sent claimant email: event=%s claim_id=%s", event, claim_id)
        else:
            _log_delivery_failure(
                channel="email",
                event=event,
                claim_id=claim_id,
                detail=f"status={response.status_code}",
            )
            _report_delivery_failure(
                channel="email",
                event=event,
                claim_id=claim_id,
                status_code=response.status_code,
            )
    except httpx.HTTPError as e:
        _log_delivery_failure(channel="email", event=event, claim_id=claim_id, detail=str(e))
        _report_delivery_failure(channel="email", event=event, claim_id=claim_id, error=str(e))


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
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as client:
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
            _log_delivery_failure(
                channel="sms",
                event=event,
                claim_id=claim_id,
                detail=f"status={response.status_code}",
            )
            _report_delivery_failure(
                channel="sms",
                event=event,
                claim_id=claim_id,
                status_code=response.status_code,
            )
    except httpx.HTTPError as e:
        _log_delivery_failure(channel="sms", event=event, claim_id=claim_id, detail=str(e))
        _report_delivery_failure(channel="sms", event=event, claim_id=claim_id, error=str(e))


def _log_delivery_failure(*, channel: str, event: str, claim_id: str, detail: str) -> None:
    """Log a delivery failure at ERROR for UCSPA-required events, WARNING otherwise."""
    if event in UCSPA_REQUIRED_EVENTS:
        logger.error(
            "Failed claimant %s delivery (UCSPA-required): event=%s claim_id=%s %s",
            channel,
            event,
            claim_id,
            detail,
        )
    else:
        logger.warning(
            "Failed claimant %s delivery: event=%s claim_id=%s %s",
            channel,
            event,
            claim_id,
            detail,
        )
