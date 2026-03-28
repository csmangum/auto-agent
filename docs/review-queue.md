# Review queue: workbench UI and API

Human-in-the-loop claims use `status = needs_review`. The backend exposes a review queue and adjuster actions; the React dashboard consumes the queue on the **workbench**.

## Implemented UI

| Area | Route | Behavior |
|------|-------|----------|
| Assignment queue | `/workbench/queue` | Lists review-queue claims with filters (priority, assignee, older-than), pagination, and **assign** (`PATCH /api/v1/claims/{id}/assign`). Links to claim detail for deeper actions. |
| Workbench home | `/workbench` | Summary cards and shortcuts including “My assignments” / queue links (`useReviewQueue`). |

Implementation: [`frontend/src/pages/AssignmentQueue.tsx`](../frontend/src/pages/AssignmentQueue.tsx), [`frontend/src/pages/WorkbenchDashboard.tsx`](../frontend/src/pages/WorkbenchDashboard.tsx).

## API (summary)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/claims/review-queue` | List claims needing review. Query: `assignee`, `priority`, `older_than_hours`, `limit`, `offset` |
| `PATCH /api/v1/claims/{claim_id}/assign` | Assign claim to adjuster |
| `POST /api/v1/claims/{claim_id}/review/approve` | Approve and re-run workflow (supervisor) |
| `POST /api/v1/claims/{claim_id}/review/reject` | Reject (`reason` in body) |
| `POST /api/v1/claims/{claim_id}/review/request-info` | Request info (`note` in body) |
| `POST /api/v1/claims/{claim_id}/review/escalate-to-siu` | Escalate to SIU |

Full detail: [adjuster-workflow.md](adjuster-workflow.md).

**CLI** (all actions): `claim-agent review-queue`, `assign`, `approve`, `reject`, `request-info`, `escalate-siu` — see [index.md](index.md#cli-commands).

## Frontend gaps

The workbench queue **does not** yet call `POST …/review/approve`, `…/reject`, `…/request-info`, or `…/escalate-to-siu`; those remain API- and CLI-only until corresponding UI is added (e.g. row or claim-detail actions using new `client.ts` helpers).

## Claim type fields

The frontend `Claim` type includes review queue fields: `priority`, `due_at`, `assignee`, `siu_case_id`, `review_started_at`. These are returned by the backend for list and detail endpoints.

## Related

- [adjuster-workflow.md](adjuster-workflow.md) – API, CLI, audit trail
- [frontend/src/api/types.ts](../frontend/src/api/types.ts) – Claim interface
- [frontend/src/api/client.ts](../frontend/src/api/client.ts) – `getReviewQueue` and review actions
