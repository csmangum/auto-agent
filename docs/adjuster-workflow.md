# Adjuster Workflow: Review Queue and Human-in-the-Loop

Claims escalated to `needs_review` enter a review queue for human adjusters. This document describes the workflow, API endpoints, CLI commands, and data model.

## Overview

When the router or escalation logic determines a claim needs human review (e.g. low confidence, high value, ambiguous duplicate, fraud indicators), the claim status is set to `needs_review` and the workflow stops. Adjusters use the review queue to:

1. List claims needing review
2. Assign claims to themselves or colleagues
3. Take action: approve, reject, request more info, or escalate to SIU

All adjuster actions are logged to the audit trail for compliance.

## Review Queue

Claims with `status = needs_review` appear in the review queue. Each claim includes:

| Field | Description |
|-------|-------------|
| `priority` | critical, high, medium, or low (from escalation logic) |
| `due_at` | SLA target datetime (critical/high: 24h, medium: 48h, low: 72h) |
| `assignee` | Adjuster ID if assigned |
| `review_started_at` | When the claim entered the queue |

The queue is ordered by priority (critical first) and due date.

## Adjuster Actions

| Action | Description | Result |
|--------|-------------|--------|
| **approve** | Approve claim for continued processing | Re-runs the full workflow (router + crew) |
| **reject** | Reject the claim | Sets status to `denied`, stores reason in audit |
| **request_info** | Request more info from claimant | Sets status to `pending_info`, stores note in audit |
| **escalate_to_siu** | Refer to Special Investigations Unit | Sets status to `under_investigation` |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/claims/review-queue` | List claims needing review. Query params: `assignee`, `priority`, `older_than_hours` |
| PATCH | `/api/claims/{claim_id}/assign` | Assign claim. Body: `{ "assignee": "user-123" }` |
| POST | `/api/claims/{claim_id}/review/approve` | Approve and reprocess (supervisor+) |
| POST | `/api/claims/{claim_id}/review/reject` | Reject. Body: `{ "reason": "..." }` |
| POST | `/api/claims/{claim_id}/review/request-info` | Request info. Body: `{ "note": "..." }` |
| POST | `/api/claims/{claim_id}/review/escalate-to-siu` | Escalate to SIU |

All require adjuster role; approve requires supervisor role.

## CLI Commands

```bash
# List claims needing review
claim-agent review-queue
claim-agent review-queue --assignee user-123 --priority high

# Assign claim to adjuster
claim-agent assign CLM-XXXXXXXX adjuster-id

# Approve and reprocess (supervisor)
claim-agent approve CLM-XXXXXXXX

# Reject with reason
claim-agent reject CLM-XXXXXXXX --reason "Duplicate claim"

# Request more info
claim-agent request-info CLM-XXXXXXXX --note "Please provide photos of damage"

# Escalate to SIU
claim-agent escalate-siu CLM-XXXXXXXX
```

## Audit Trail

Each adjuster action writes to `claim_audit_log`:

- **approve**: `action=approval`, details="Approved for continued processing"
- **reject**: `action=status_change` (needs_review → denied), `action=rejection` with reason
- **request_info**: `action=status_change` (needs_review → pending_info), `action=request_info` with note
- **escalate_to_siu**: `action=status_change` (needs_review → under_investigation), `action=escalate_to_siu`
- **assign**: `action=assign`, before_state/after_state with assignee

The `actor_id` column stores the authenticated adjuster identity (from API key or JWT).

## Related

- [Database Schema](database.md) – claims table, audit log, status constants
- [logic.py](../src/claim_agent/tools/logic.py) – `evaluate_escalation_impl`, priority computation
- [main_crew.py](../src/claim_agent/crews/main_crew.py) – escalation detection and workflow
