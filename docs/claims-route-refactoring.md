# Claims route refactoring

`src/claim_agent/api/routes/claims.py` is a large module with many endpoints. This document describes the intended split and shared infrastructure.

## Shared helpers

[`src/claim_agent/api/routes/_claims_helpers.py`](../src/claim_agent/api/routes/_claims_helpers.py) holds cross-cutting logic used by the claims router and portal routes:

- Constants: `ALLOWED_DOCUMENT_EXTENSIONS`, `VALID_DOCUMENT_TYPES`, `STREAM_POLL_INTERVAL`, `STREAM_MAX_DURATION`, `PRIORITY_VALUES`, `ALLOWED_SORT_FIELDS`
- Process state: `background_tasks`, `background_tasks_lock`, `task_claim_ids`, `approve_locks`
- Request models: `GenerateClaimRequest`, `GenerateIncidentDetailsRequest`
- Helpers: `get_claim_context`, `http_already_processing`, upload size helpers, adjuster scoping, approve locks, background workflow scheduling, attachment URL resolution, document repository helpers, incident sanitization, claim creation with attachments, SSE streaming

The main router imports these symbols (often with `_` aliases) from `_claims_helpers`. Graceful shutdown uses `background_tasks` and `task_claim_ids` from `_claims_helpers` (see `server.py`).

## Target route modules (future)

Rough grouping for splitting `claims.py` into focused routers:

| Module | Focus |
|--------|--------|
| claims_crud | Stats, list, review queue, status, detail, create |
| claims_review | Assign, acknowledge, approve, reject, request-info, escalate, review |
| claims_workflow | Process, async process, stream, reprocess |
| claims_specialized | Follow-up, SIU, dispute, denial/coverage, supplemental |
| claims_documents | Attachments, documents, document requests |
| claims_parties | Consent, relationships, portal tokens, repair shops |
| claims_incidents | Incidents, links, related claims, BI allocation |
| claims_financial | Reserves, litigation hold, repair status |
| claims_audit | History, notes, fraud filings, workflows |
| claims_mock | Mock claim generation (requires `MOCK_CREW_ENABLED`) |

## Integration pattern

After split modules exist, register each `APIRouter` in `server.py` with `prefix="/api/v1"`, mirroring the current single `claims` router registration.

## Testing

Use `.venv/bin/pytest` with `MOCK_DB_PATH=data/mock_db.json`. Unit and integration tests mock the LLM; no API key required.
