# Claims Route Refactoring Plan

## Current State

The `src/claim_agent/api/routes/claims.py` file is **2,873 lines long** and handles 58 different route endpoints, making it difficult to maintain and navigate.

## Analysis Completed

### Route Distribution

The 58 routes break down into these logical groups:

| Module | Routes | Description |
|--------|--------|-------------|
| **claims_crud** | 6 | Core CRUD: stats, list, review queue, status, detail, create |
| **claims_review** | 7 | Review workflow: assign, acknowledge, approve, reject, request-info, escalate, review |
| **claims_workflow** | 4 | Processing: process, async process, stream updates, reprocess |
| **claims_specialized** | 7 | Specialized workflows: follow-up, SIU, dispute, denial/coverage, supplemental |
| **claims_documents** | 7 | Documents: attachments, documents, document requests |
| **claims_parties** | 9 | Parties & portals: consent, relationships, portal tokens (3 types), repair shops |
| **claims_incidents** | 5 | Incidents: create, detail, links, related claims, BI allocation |
| **claims_financial** | 6 | Financial: reserves, litigation hold, repair status |
| **claims_audit** | 5 | Audit & history: history, notes, fraud filings, workflows |
| **claims_mock** | 2 | Mock generation (testing): generate claims, generate incident details |

### Code Distribution

- **Route functions**: ~443 lines (route decorators + signatures + bodies)
- **Helper functions**: ~250 lines (15 private helper functions)
- **Model classes**: ~300 lines (27 Pydantic request/response models)
- **Imports & setup**: ~100 lines  
- **Constants**: ~50 lines
- **Supporting code**: ~1,730 lines

## Work Completed

### 1. Shared Helpers Module Created ✅

Created `src/claim_agent/api/routes/_claims_helpers.py` (284 lines) with:

- **Constants**: `ALLOWED_DOCUMENT_EXTENSIONS`, `VALID_DOCUMENT_TYPES`, `STREAM_POLL_INTERVAL`, `STREAM_MAX_DURATION`, `PRIORITY_VALUES`, `ALLOWED_SORT_FIELDS`
- **State management**: `background_tasks`, `background_tasks_lock`, `task_claim_ids`, `approve_locks`
- **Pydantic models**: `GenerateClaimRequest`, `GenerateIncidentDetailsRequest`
- **Helper functions**:
  - `get_claim_context()` - FastAPI dependency
  - `http_already_processing()` - HTTP 409 handler
  - `max_upload_file_size_bytes()` - File size limits
  - `upload_file_size_exceeded_detail()` - Error messages
  - `adjuster_scope_params()` - Access control
  - `apply_adjuster_claim_filter()` - Query filtering
  - `get_approve_lock()` - Concurrency control
  - `run_workflow_background()` - Background task execution
  - `try_run_workflow_background()` - With capacity checking
  - `resolve_attachment_urls()` - URL resolution for S3/local storage
  - `get_doc_repo()` - Document repository factory
  - `maybe_update_document_request_on_receipt()` - Document request completion
  - `sanitize_incident_data()` - Input sanitization
  - `process_claim_with_attachments()` - Claim creation with file uploads
  - `prepare_claim_for_workflow()` - Workflow data preparation
  - `stream_claim_updates()` - SSE streaming generator

### 2. Analysis Scripts Created ✅

- `split_claims_analysis.py` - Categorizes all 58 routes
- `split_claims_routes.py` - Defines module assignments
- `extract_and_place_models.py` - Maps Pydantic models to modules
- `fix_route_extraction.py` - Function body extraction logic

### 3. Route-to-Module Mapping Defined ✅

Each of the 58 routes has been assigned to its target module with clear ownership.

## Recommended Next Steps

### Phase 1: Manual Module Creation (High Priority)

Given the complexity of automated extraction, **manual creation** of the 10 route modules is recommended:

1. **Start with smallest modules** (claims_mock, claims_incidents)
2. **Copy route functions** from claims.py to new module files
3. **Copy associated Pydantic models** inline in each module
4. **Import from _claims_helpers** instead of duplicating code
5. **Test each module** individually before proceeding

### Phase 2: Server Integration

Update `src/claim_agent/api/server.py`:

```python
from claim_agent.api.routes.claims_crud import router as claims_crud_router
from claim_agent.api.routes.claims_review import router as claims_review_router
from claim_agent.api.routes.claims_workflow import router as claims_workflow_router
# ... (8 more imports)

# Register routers
app.include_router(claims_crud_router, prefix="/api/v1")
app.include_router(claims_review_router, prefix="/api/v1")
app.include_router(claims_workflow_router, prefix="/api/v1")
# ... (8 more registrations)
```

### Phase 3: Deprecate Original File

Two options:

**Option A (Conservative)**: Keep `claims.py` temporarily
- Rename to `claims_legacy.py`
- Add deprecation warnings
- Remove after 1-2 releases

**Option B (Clean Break)**: Delete immediately
- Remove `claims.py`
- Update all imports
- Run full test suite

### Phase 4: Testing

1. **Unit tests**: Verify each module independently
2. **Integration tests**: Run full E2E test suite
3. **API tests**: Hit every endpoint via HTTP
4. **Load tests**: Ensure no performance regression

## Benefits of Split

### Maintainability
- **Smaller files** (~150-200 lines each vs. 2,873)
- **Focused modules** (single responsibility)
- **Easier navigation** (logical grouping)

### Development Velocity
- **Parallel work** (multiple devs, no conflicts)
- **Faster reviews** (smaller diffs)
- **Reduced cognitive load** (understand one domain at a time)

### Code Quality
- **Clear boundaries** (explicit dependencies)
- **Better testing** (module-level test files)
- **Easier refactoring** (isolated changes)

## Migration Checklist

- [ ] Create `claims_crud.py` (6 routes)
- [ ] Create `claims_review.py` (7 routes)
- [ ] Create `claims_workflow.py` (4 routes)
- [ ] Create `claims_specialized.py` (7 routes)
- [ ] Create `claims_documents.py` (7 routes)
- [ ] Create `claims_parties.py` (9 routes)
- [ ] Create `claims_incidents.py` (5 routes)
- [ ] Create `claims_financial.py` (6 routes)
- [ ] Create `claims_audit.py` (5 routes)
- [ ] Create `claims_mock.py` (2 routes)
- [ ] Update `server.py` to register all new routers
- [ ] Remove/deprecate original `claims.py`
- [ ] Update imports in test files
- [ ] Run full test suite
- [ ] Update documentation

## Notes

- **Backwards compatibility**: Not required per AGENTS.md
- **Testing**: Use `.venv/bin/pytest` with `MOCK_DB_PATH=data/mock_db.json`
- **No API key needed**: Unit/integration tests mock the LLM
- **Line limit**: Ruff enforces 100 chars
