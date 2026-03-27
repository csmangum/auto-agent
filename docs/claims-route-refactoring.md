# Claims route refactoring

`src/claim_agent/api/routes/claims.py` previously held most adjuster claim endpoints. Focused routers and shared helpers now split that surface area; this document describes the layout.

## Shared helpers

[`src/claim_agent/api/routes/_claims_helpers.py`](../src/claim_agent/api/routes/_claims_helpers.py) holds cross-cutting logic used by the claims routers and portal routes:

- Constants: `ALLOWED_DOCUMENT_EXTENSIONS`, `VALID_DOCUMENT_TYPES`, `STREAM_POLL_INTERVAL`, `STREAM_MAX_DURATION`, `PRIORITY_VALUES`, `ALLOWED_SORT_FIELDS`
- Process state: `background_tasks`, `background_tasks_lock`, `task_claim_ids`, `approve_locks`
- Request models: `GenerateClaimRequest`, `GenerateIncidentDetailsRequest`
- Helpers: `get_claim_context`, `http_already_processing`, upload size helpers, adjuster scoping, approve locks, background workflow scheduling (`run_workflow_background`, `try_run_workflow_background`, `background_workflow_queue_full`), attachment URL resolution, document repository helpers, incident sanitization, claim creation with attachments, SSE streaming

The legacy `claims` router and the split routers import these symbols (often with `_` aliases) from `_claims_helpers`. Graceful shutdown uses `background_tasks` and `task_claim_ids` from `_claims_helpers` (see `server.py`).

## Implemented route modules

These `APIRouter` instances are registered in [`server.py`](../src/claim_agent/api/server.py) with `prefix="/api/v1"`, **in this order** (static paths like `/claims/stats` must register before `/claims/{claim_id}`):

| Module | File | Focus |
|--------|------|--------|
| `claims_crud_router` | [`claims_crud.py`](../src/claim_agent/api/routes/claims_crud.py) | Stats, list, review queue, status, detail, create |
| `claims_review_router` | [`claims_review.py`](../src/claim_agent/api/routes/claims_review.py) | Assign, acknowledge, approve, reject, request-info, escalate, review |
| `claims_router` | [`claims.py`](../src/claim_agent/api/routes/claims.py) | Follow-up, SIU, dispute, denial/coverage, supplemental, documents, parties, incidents, reserves, audit, mock generation, etc. |
| `claims_workflow_router` | [`claims_workflow.py`](../src/claim_agent/api/routes/claims_workflow.py) | Process, async process, stream, reprocess |

All use `tags=["claims"]` for OpenAPI grouping.

## Further splits (optional)

Rough grouping if `claims.py` is split again:

| Module | Focus |
|--------|--------|
| claims_specialized | Follow-up, SIU, dispute, denial/coverage, supplemental |
| claims_documents | Attachments, documents, document requests |
| claims_parties | Consent, relationships, portal tokens, repair shops |
| claims_incidents | Incidents, links, related claims, BI allocation |
| claims_financial | Reserves, litigation hold, repair status |
| claims_audit | History, notes, fraud filings, workflows |
| claims_mock | Mock claim generation (requires `MOCK_CREW_ENABLED`) |

## Testing

Use `.venv/bin/pytest` with `MOCK_DB_PATH=data/mock_db.json`. Focused API coverage: `tests/test_api_claims.py`, `tests/test_api_claims_review.py`, `tests/test_api_claims_workflow.py`. Unit and integration tests mock the LLM; no API key required.
