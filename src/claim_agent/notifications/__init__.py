"""Notifications: webhooks, claimant email/SMS, shop notifications."""

from claim_agent.notifications.claimant import notify_claimant
from claim_agent.notifications.webhook import (
    dispatch_claim_event,
    dispatch_repair_authorized,
    dispatch_webhook,
)

__all__ = [
    "dispatch_claim_event",
    "dispatch_repair_authorized",
    "dispatch_webhook",
    "notify_claimant",
]
