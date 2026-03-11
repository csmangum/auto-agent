"""User-type-specific notifications for follow-up agent.

Extends the notify_claimant pattern to support different user types
(claimant, policyholder, repair_shop, etc.) with appropriate channels.
Stub implementation: logs intent. Real integration via adapters.
"""

import logging
from typing import Any

from claim_agent.config.settings import get_notification_config
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
) -> None:
    """Send follow-up message to a user based on their type.

    Routes to the appropriate channel for each user type:
    - claimant, policyholder: email/SMS via claimant adapter
    - repair_shop: portal/API (stub)
    - adjuster, siu: internal (stub)
    - other: generic (stub)

    Args:
        user_type: One of claimant, policyholder, adjuster, repair_shop, siu, other.
        claim_id: Claim ID.
        message: Message content to send.
        email: Optional email for outreach.
        phone: Optional phone for SMS.
        identifier: Optional user/contact identifier.
        template_data: Optional template variables.
    """
    config = get_notification_config()
    if not config["email_enabled"] and not config["sms_enabled"]:
        return

    try:
        ut = UserType(user_type)
    except ValueError:
        logger.warning("Unknown user_type for notify_user: %s", user_type)
        return

    if ut in (UserType.CLAIMANT, UserType.POLICYHOLDER):
        if email or phone:
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
    elif ut == UserType.REPAIR_SHOP:
        logger.info(
            "Would send follow-up to repair_shop via portal/API: claim_id=%s identifier=%s (stub)",
            claim_id,
            identifier,
        )
    elif ut in (UserType.ADJUSTER, UserType.SIU):
        logger.info(
            "Would send internal follow-up to %s: claim_id=%s (stub)",
            user_type,
            claim_id,
        )
    else:
        logger.info(
            "Would send follow-up to %s: claim_id=%s (stub)",
            user_type,
            claim_id,
        )
