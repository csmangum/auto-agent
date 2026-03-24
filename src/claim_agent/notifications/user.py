"""User-type-specific notifications for follow-up agent.

Extends the notify_claimant pattern to support different user types
(claimant, policyholder, repair_shop, etc.) with appropriate channels.
Stub implementation: logs intent. Real integration via adapters.
"""

import logging
from typing import Any

from claim_agent.config.settings import get_mock_crew_config, get_mock_notifier_config, get_notification_config
from claim_agent.models.user import UserType
from claim_agent.notifications.claimant import notify_claimant

logger = logging.getLogger(__name__)


def notify_user(
    user_type: str,
    claim_id: str,
    message: str,
    *,
    email: str | None = None,
    phone: str | None = None,
    identifier: str | None = None,
    template_data: dict[str, Any] | None = None,
) -> bool:
    """Send follow-up message to a user based on their type.

    Routes to the appropriate channel for each user type:
    - claimant, policyholder, witness, attorney: email/SMS via claimant adapter
    - repair_shop: portal/API (stub)
    - adjuster, siu: internal (stub)
    - other: generic (stub)

    Args:
        user_type: claimant, policyholder, witness, attorney, adjuster, repair_shop, siu, other.
        claim_id: Claim ID.
        message: Message content to send.
        email: Optional email for outreach.
        phone: Optional phone for SMS.
        identifier: Optional user/contact identifier.
        template_data: Optional template variables.

    Returns:
        True if delivery was attempted (or queued); False if skipped (e.g., no
        contact channels for claimant/policyholder, or notifications disabled).
    """
    try:
        ut = UserType(user_type)
    except ValueError:
        logger.warning("Unknown user_type for notify_user: %s", user_type)
        return False

    # Mock intercept: suppress real notifications during testing
    if get_mock_crew_config()["enabled"] and get_mock_notifier_config()["enabled"]:
        from claim_agent.mock_crew.notifier import mock_notify_user

        mock_notify_user(
            user_type,
            claim_id,
            message,
            template_data=template_data,
        )
        return True  # pretend delivered so mark_follow_up_sent runs

    if ut in (UserType.CLAIMANT, UserType.POLICYHOLDER, UserType.WITNESS, UserType.ATTORNEY):
        config = get_notification_config()
        if not config["email_enabled"] and not config["sms_enabled"]:
            logger.debug(
                "Both email and SMS disabled; skipping follow-up notification for %s claim_id=%s",
                user_type,
                claim_id,
            )
            return False
        if not email and not phone:
            logger.debug(
                "No email or phone for %s; skipping follow-up for claim_id=%s",
                user_type,
                claim_id,
            )
            return False
        notify_claimant(
            "follow_up_request",
            claim_id,
            email=email,
            phone=phone,
            template_data=template_data or {"message": message},
        )
        logger.info(
            "Would send follow-up to %s: claim_id=%s (stub)",
            user_type,
            claim_id,
        )
        return True
    elif ut == UserType.REPAIR_SHOP:
        logger.info(
            "Would send follow-up to repair_shop via portal/API: claim_id=%s identifier=%s (stub)",
            claim_id,
            identifier,
        )
        return True
    elif ut in (UserType.ADJUSTER, UserType.SIU):
        logger.info(
            "Would send internal follow-up to %s: claim_id=%s (stub)",
            user_type,
            claim_id,
        )
        return True
    else:
        logger.info(
            "Would send follow-up to %s: claim_id=%s (stub)",
            user_type,
            claim_id,
        )
        return True
