"""Shared HTTP response hint values for the API layer."""

CLAIM_ALREADY_PROCESSING_RETRY_AFTER = "30"
BACKGROUND_QUEUE_FULL_RETRY_AFTER = "60"
BACKGROUND_QUEUE_FULL_DETAIL = (
    "Too many concurrent background workflow tasks; try again later."
)
