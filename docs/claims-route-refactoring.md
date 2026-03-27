# Claims route refactoring

`src/claim_agent/api/routes/claims.py` previously held most adjuster claim endpoints. Focused routers and shared helpers now split that surface area; **`claims.py` now only registers Mock Crew routes** (`POST /claims/generate`, `POST /claims/generate-incident-details`). This document describes the layout.

## Shared helpers

[`src/claim_agent/api/routes/_claims_helpers.py`](../src/claim_agent/api/routes/_claims_helpers.py) holds cross-cutting logic used by the claims routers and portal routes:

- Constants: `ALLOWED_DOCUMENT_EXTENSIONS`, `VALID_DOCUMENT_TYPES`, `STREAM_POLL_INTERVAL`, `STREAM_MAX_DURATION`, `PRIORITY_VALUES`, `ALLOWED_SORT_FIELDS`, `CLAIM_ALREADY_PROCESSING_RETRY_AFTER`, `BACKGROUND_QUEUE_FULL_RETRY_AFTER`
- Process state: `background_tasks`, `background_tasks_lock`, `task_claim_ids`, `approve_locks`
- Request models: `GenerateClaimRequest`, `GenerateIncidentDetailsRequest`
- Helpers: `get_claim_context`, `http_already_processing`, upload size helpers, adjuster scoping, approve locks, background workflow scheduling (`run_workflow_background`, `try_run_workflow_background`, `background_workflow_queue_full`), attachment URL resolution, document repository helpers, incident sanitization, claim creation with attachments, SSE streaming

The claims routers and portal routes import these symbols (often with `_` aliases) from `_claims_helpers`. Graceful shutdown uses `background_tasks` and `task_claim_ids` from `_claims_helpers` (see `server.py`).

## Implemented route modules

These `APIRouter` instances are registered in [`server.py`](../src/claim_agent/api/server.py) with `prefix="/api/v1"`, **in this order** (static paths like `/claims/stats` must register before `/claims/{claim_id}`):

| Module | File | Focus |
|--------|------|--------|
| `claims_crud_router` | [`claims_crud.py`](../src/claim_agent/api/routes/claims_crud.py) | Stats, list, review queue, status, detail, create |
| `claims_audit_router` | [`claims_audit.py`](../src/claim_agent/api/routes/claims_audit.py) | History, fraud filings, notes, workflows |
| `claims_review_router` | [`claims_review.py`](../src/claim_agent/api/routes/claims_review.py) | Assign, acknowledge, approve, reject, request-info, escalate, compliance review |
| `claims_router` | [`claims.py`](../src/claim_agent/api/routes/claims.py) | Mock claim generation only (`MOCK_CREW_ENABLED`) |
| `claims_financial_router` | [`claims_financial.py`](../src/claim_agent/api/routes/claims_financial.py) | Reserves, litigation hold, repair status |
| `claims_parties_router` | [`claims_parties.py`](../src/claim_agent/api/routes/claims_parties.py) | Consent, relationships, portal tokens, repair shops |
| `claims_documents_router` | [`claims_documents.py`](../src/claim_agent/api/routes/claims_documents.py) | Attachments, documents, document requests |
| `claims_workflow_router` | [`claims_workflow.py`](../src/claim_agent/api/routes/claims_workflow.py) | Process, async process, stream, reprocess |
| `claims_specialized_router` | [`claims_specialized.py`](../src/claim_agent/api/routes/claims_specialized.py) | Follow-up, SIU, dispute, denial/coverage, supplemental |
| `claims_incidents_router` | [`claims_incidents.py`](../src/claim_agent/api/routes/claims_incidents.py) | Incidents, claim links, related claims, BI allocation |

All use `tags=["claims"]` for OpenAPI grouping.

## Shared constants

[`_claims_helpers.py`](../src/claim_agent/api/routes/_claims_helpers.py) also exports HTTP hint constants: `CLAIM_ALREADY_PROCESSING_RETRY_AFTER` (409), `BACKGROUND_QUEUE_FULL_RETRY_AFTER` (503 when the background workflow queue is full).

## Testing

Use `.venv/bin/pytest` with `MOCK_DB_PATH=data/mock_db.json`. Focused API coverage: `tests/test_api_claims.py`, `tests/test_api_claims_review.py`, `tests/test_api_claims_workflow.py`, `tests/test_api_claims_audit.py`, `tests/test_api_claims_documents.py`, `tests/test_api_claims_financial.py`, `tests/test_api_claims_incidents.py`, `tests/test_api_claims_parties.py`, `tests/test_api_server_boot.py` (app import + no duplicate routes). Unit and integration tests mock the LLM; no API key required.
