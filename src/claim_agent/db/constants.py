"""Claim status constants.

Statuses disputed, fraud_suspected, fraud_confirmed, partial_loss, under_investigation,
denied, and settled are reserved for future workflows (e.g. fraud, dispute, partial-loss
crews) and are not yet set by the main router/workflow.
"""

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_DUPLICATE = "duplicate"
STATUS_FAILED = "failed"
STATUS_DISPUTED = "disputed"
STATUS_FRAUD_SUSPECTED = "fraud_suspected"
STATUS_FRAUD_CONFIRMED = "fraud_confirmed"
STATUS_PARTIAL_LOSS = "partial_loss"
STATUS_UNDER_INVESTIGATION = "under_investigation"
STATUS_DENIED = "denied"
STATUS_SETTLED = "settled"
STATUS_NEEDS_REVIEW = "needs_review"

# All allowed claim statuses (single source of truth for validation/docs)
CLAIM_STATUSES = (
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_OPEN,
    STATUS_CLOSED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_DISPUTED,
    STATUS_FRAUD_SUSPECTED,
    STATUS_FRAUD_CONFIRMED,
    STATUS_PARTIAL_LOSS,
    STATUS_UNDER_INVESTIGATION,
    STATUS_DENIED,
    STATUS_SETTLED,
    STATUS_NEEDS_REVIEW,
)
