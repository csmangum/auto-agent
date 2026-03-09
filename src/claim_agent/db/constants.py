"""Claim status constants.

`fraud_suspected` and `settled` are used by the main router/workflow for
fraud and post-settlement outcomes.  `disputed` and `dispute_resolved` are
used by the policyholder dispute workflow.
"""

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_OPEN = "open"
STATUS_CLOSED = "closed"
STATUS_DUPLICATE = "duplicate"
STATUS_FAILED = "failed"
STATUS_DISPUTED = "disputed"
STATUS_DISPUTE_RESOLVED = "dispute_resolved"
STATUS_FRAUD_SUSPECTED = "fraud_suspected"
STATUS_FRAUD_CONFIRMED = "fraud_confirmed"
STATUS_PARTIAL_LOSS = "partial_loss"
STATUS_UNDER_INVESTIGATION = "under_investigation"
STATUS_DENIED = "denied"
STATUS_SETTLED = "settled"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_PENDING_INFO = "pending_info"
STATUS_ARCHIVED = "archived"

# Statuses that allow filing a policyholder dispute (must have completed workflow)
DISPUTABLE_STATUSES = (STATUS_SETTLED, STATUS_OPEN)

# Statuses that allow supplemental damage reports (partial loss during or after repair)
SUPPLEMENTABLE_STATUSES = (STATUS_PROCESSING, STATUS_SETTLED)

# Statuses that allow denial/coverage dispute workflow (denied claims)
DENIAL_COVERAGE_STATUSES = (STATUS_DENIED,)

# All allowed claim statuses (single source of truth for validation/docs)
CLAIM_STATUSES = (
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_OPEN,
    STATUS_CLOSED,
    STATUS_DUPLICATE,
    STATUS_FAILED,
    STATUS_DISPUTED,
    STATUS_DISPUTE_RESOLVED,
    STATUS_FRAUD_SUSPECTED,
    STATUS_FRAUD_CONFIRMED,
    STATUS_PARTIAL_LOSS,
    STATUS_UNDER_INVESTIGATION,
    STATUS_DENIED,
    STATUS_SETTLED,
    STATUS_NEEDS_REVIEW,
    STATUS_PENDING_INFO,
    STATUS_ARCHIVED,
)
