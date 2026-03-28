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

When you **approve** a claim, the system (1) runs the Human Review Handback crew to parse any reviewer decision (confirmed_claim_type, confirmed_payout, notes) and update the claim, then (2) re-runs the main workflow to route to settlement, subrogation, or the appropriate crew. Optional reviewer decision fields let you override the router classification or payout for handback.

| Action | Description | Result |
|--------|-------------|--------|
| **approve** | Approve claim for continued processing | Runs Human Review Handback crew to parse reviewer decision (optional: confirmed_claim_type, confirmed_payout, notes), then re-runs main workflow |
| **reject** | Reject the claim | Sets status to `denied`, stores reason in audit |
| **request_info** | Request more info from claimant | Sets status to `pending_info`, stores note in audit |
| **escalate_to_siu** | Refer to Special Investigations Unit | Sets status to `under_investigation` |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/claims/review-queue` | List claims needing review. Query params: `assignee`, `priority`, `older_than_hours` |
| PATCH | `/api/v1/claims/{claim_id}/assign` | Assign claim. Body: `{ "assignee": "user-123" }` |
| POST | `/api/v1/claims/{claim_id}/review/approve` | Approve and reprocess (supervisor+). Optional body: `{ "reviewer_decision": { "confirmed_claim_type": "...", "confirmed_payout": N, "notes": "..." } }` |
| POST | `/api/v1/claims/{claim_id}/review/reject` | Reject. Body: `{ "reason": "..." }` |
| POST | `/api/v1/claims/{claim_id}/review/request-info` | Request info. Body: `{ "note": "..." }` |
| POST | `/api/v1/claims/{claim_id}/review/escalate-to-siu` | Escalate to SIU |

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
claim-agent approve CLM-XXXXXXXX --confirmed-claim-type partial_loss --confirmed-payout 5000 --notes "Reviewed and confirmed"

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

## Workbench UI Routes

The frontend adjuster workbench maps to the following routes and API endpoints (see [#309](https://github.com/csmangum/auto-agent/issues/309) for the full feature checklist).

| Capability | Frontend Route | API Endpoints |
|------------|---------------|---------------|
| **Workbench dashboard** | `/workbench` | — |
| **Assignment / review queue** | `/workbench/queue` | `GET /api/v1/claims/review-queue`, `PATCH /api/v1/claims/{id}/assign` |
| **Diary / calendar** | `/workbench/diary` | `GET /api/v1/tasks`, `GET /api/v1/tasks/overdue`, `GET /api/v1/diary/compliance-templates` |
| **Per-claim detail** | `/claims/:claimId` | `GET /api/v1/claims/{id}` |
| — Notes | `/claims/:claimId` (Notes tab) | `GET/POST /api/v1/claims/{id}/notes` |
| — Documents | `/claims/:claimId` (Documents tab) | `GET/POST /api/v1/claims/{id}/documents`, `GET/POST /api/v1/claims/{id}/document-requests` |
| — Reserves | `/claims/:claimId` (Reserves tab) | `PATCH /api/v1/claims/{id}/reserve`, `GET /api/v1/claims/{id}/reserve-history`, `GET /api/v1/claims/{id}/reserve/adequacy` |
| — Payments | `/claims/:claimId` (Payments tab) | `GET/POST /api/v1/claims/{id}/payments`, `POST .../payments/{pid}/issue` |
| — Communications / follow-up | `/claims/:claimId` (Comms tab) | `GET/POST /api/v1/claims/{id}/follow-up`, `POST /api/v1/claims/{id}/follow-up/record-response` |
| — Coverage / denial | `/claims/:claimId` (Coverage tab) | `POST /api/v1/claims/{id}/denial-coverage` |

## Related

- [Database Schema](database.md) – claims table, audit log, status constants
- [logic.py](../src/claim_agent/tools/logic.py) – `evaluate_escalation_impl`, priority computation
- [orchestrator.py](../src/claim_agent/workflow/orchestrator.py) – workflow execution (`run_claim_workflow`)
- [workflow/helpers.py](../src/claim_agent/workflow/helpers.py) – workflow stages and checkpoint invalidation (used when resuming from a stage)
