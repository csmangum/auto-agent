"""Audit event types for claim_audit_log.

Standardized event types for compliance and querying. All audit records are
append-only (no UPDATE or DELETE). See docs/database.md for schema and retention.
"""

# Event types (action column)
AUDIT_EVENT_CREATED = "created"
AUDIT_EVENT_STATUS_CHANGE = "status_change"
AUDIT_EVENT_APPROVAL = "approval"
AUDIT_EVENT_REJECTION = "rejection"
AUDIT_EVENT_REPROCESS = "reprocess"
AUDIT_EVENT_ESCALATION = "escalation"
AUDIT_EVENT_PAYOUT_SET = "payout_set"
AUDIT_EVENT_ATTACHMENTS_UPDATED = "attachments_updated"

# Actor identifiers for automated actions
ACTOR_SYSTEM = "system"
ACTOR_WORKFLOW = "workflow"

# All event types (for validation/docs)
AUDIT_EVENT_TYPES = (
    AUDIT_EVENT_CREATED,
    AUDIT_EVENT_STATUS_CHANGE,
    AUDIT_EVENT_APPROVAL,
    AUDIT_EVENT_REJECTION,
    AUDIT_EVENT_REPROCESS,
    AUDIT_EVENT_ESCALATION,
    AUDIT_EVENT_PAYOUT_SET,
    AUDIT_EVENT_ATTACHMENTS_UPDATED,
)
