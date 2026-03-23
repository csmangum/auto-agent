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
STATUS_PURGED = "purged"

RETENTION_TIER_ACTIVE = "active"
RETENTION_TIER_COLD = "cold"
RETENTION_TIER_ARCHIVED = "archived"
RETENTION_TIER_PURGED = "purged"

RETENTION_TIERS = (
    RETENTION_TIER_ACTIVE,
    RETENTION_TIER_COLD,
    RETENTION_TIER_ARCHIVED,
    RETENTION_TIER_PURGED,
)

# Statuses that allow filing a policyholder dispute (must have completed workflow)
DISPUTABLE_STATUSES = (STATUS_SETTLED, STATUS_OPEN)

# Party types eligible for third-party portal tokens (not claimant/policyholder)
THIRD_PARTY_PORTAL_ELIGIBLE_PARTY_TYPES = frozenset(
    {"witness", "attorney", "provider", "lienholder"}
)

# Statuses that allow supplemental damage reports (partial loss during or after repair)
SUPPLEMENTABLE_STATUSES = (STATUS_PROCESSING, STATUS_SETTLED)

# Statuses that allow denial/coverage dispute workflow (denied claims)
DENIAL_COVERAGE_STATUSES = (STATUS_DENIED,)

# Statuses that allow SIU investigation workflow
SIU_INVESTIGATION_STATUSES = (STATUS_UNDER_INVESTIGATION, STATUS_FRAUD_SUSPECTED)

# Repair status stages for partial loss (received -> ... -> ready, paused_supplement)
VALID_REPAIR_STATUSES = frozenset({
    "received",
    "disassembly",
    "parts_ordered",
    "repair",
    "paint",
    "reassembly",
    "qa",
    "ready",
    "paused_supplement",
})

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
    STATUS_PURGED,
)

# Stable codes returned by ClaimRepository.check_reserve_adequacy (API: warning_codes)
RESERVE_ADEQUACY_CODE_NOT_SET = "RESERVE_NOT_SET"
RESERVE_ADEQUACY_CODE_BELOW_ESTIMATE = "RESERVE_BELOW_ESTIMATE"
RESERVE_ADEQUACY_CODE_BELOW_PAYOUT = "RESERVE_BELOW_PAYOUT"
RESERVE_ADEQUACY_CODE_BELOW_BENCHMARK = "RESERVE_BELOW_BENCHMARK"
