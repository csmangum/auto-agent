# Review Queue: Frontend Future Work

This document describes the intended frontend implementation for the human-in-the-loop review queue. The backend API is already implemented; see [adjuster-workflow.md](adjuster-workflow.md) for API details.

## Overview

Claims with `status = needs_review` require human review. The backend exposes a review queue API and adjuster action endpoints. The frontend does not yet consume these; this doc outlines the planned UI.

## API Summary

| Endpoint | Purpose |
|----------|---------|
| `GET /api/claims/review-queue` | List claims needing review. Filters: `assignee`, `priority`, `older_than_hours`, `limit`, `offset` |
| `PATCH /api/claims/{claim_id}/assign` | Assign claim to adjuster. Body: `{ "assignee": "user-id" }` |
| `POST /api/claims/{claim_id}/review/approve` | Approve and re-run workflow (supervisor) |
| `POST /api/claims/{claim_id}/review/reject` | Reject. Body: `{ "reason": "..." }` |
| `POST /api/claims/{claim_id}/review/request-info` | Request info from claimant. Body: `{ "note": "..." }` |
| `POST /api/claims/{claim_id}/review/escalate-to-siu` | Escalate to Special Investigations Unit |

## Intended UI Flow

1. **Review Queue page** (e.g. `/review-queue`)
   - Filter bar: assignee, priority, older-than dropdown
   - Table columns: Claim ID, Policy, VIN, Type, Status, Priority, Due, Assignee, Review Started
   - Row click navigates to claim detail
   - Row actions: Assign, Approve, Reject, Request Info, Escalate to SIU

2. **Claim detail integration**
   - For claims with `status = needs_review`, show action buttons in header or sidebar
   - Same actions as above, with modals for Assign (assignee input), Reject (reason), Request Info (note)

3. **API client additions**
   - `getReviewQueue(params)` → `GET /api/claims/review-queue`
   - `assignClaim(claimId, assignee)` → `PATCH /api/claims/{id}/assign`
   - `approveReview(claimId)` → `POST /api/claims/{id}/review/approve`
   - `rejectReview(claimId, reason)` → `POST /api/claims/{id}/review/reject`
   - `requestInfoReview(claimId, note)` → `POST /api/claims/{id}/review/request-info`
   - `escalateToSiu(claimId)` → `POST /api/claims/{id}/review/escalate-to-siu`

## Claim Type Fields

The frontend `Claim` type includes review queue fields: `priority`, `due_at`, `assignee`, `siu_case_id`, `review_started_at`. These are returned by the backend for list and detail endpoints.

## Related

- [adjuster-workflow.md](adjuster-workflow.md) – API, CLI, audit trail
- [frontend/src/api/types.ts](../frontend/src/api/types.ts) – Claim interface
- [frontend/src/api/client.ts](../frontend/src/api/client.ts) – API client
