# GitHub Issues Created for Claims.py Refactoring

## Meta-Issue
- **#756** - Complete claims.py route file split (meta-issue)
  - Tracks overall progress across all phases
  - Links to all sub-issues

## Phase 2: Module Creation (10 Issues)

Listed in recommended implementation order:

### Easy (Start Here)
1. **#753** - Create claims_mock.py (2 routes) ⭐
   - Simplest module
   - Minimal dependencies
   - Good starting point

### Simple (Read-Heavy)
2. **#752** - Create claims_audit.py (5 routes)
   - History, notes, fraud filings
   - Mostly read operations

3. **#750** - Create claims_incidents.py (5 routes)
   - Incident management
   - BI allocation

### Medium Complexity
4. **#746** - Create claims_workflow.py (4 routes)
   - Process, reprocess, streaming
   - Background task handling

5. **#751** - Create claims_financial.py (6 routes)
   - Reserves, litigation, repair status
   - Authority checks

6. **#744** - Create claims_crud.py (6 routes)
   - Core CRUD operations
   - Stats, list, detail, create

### Complex (Many Models)
7. **#745** - Create claims_review.py (7 routes)
   - Review workflow
   - 5 Pydantic models

8. **#748** - Create claims_documents.py (7 routes)
   - Documents & attachments
   - File upload handling

9. **#747** - Create claims_specialized.py (7 routes)
   - Follow-up, SIU, disputes
   - 8 Pydantic models

10. **#749** - Create claims_parties.py (9 routes)
    - Party management
    - 3 types of portal tokens

## Phase 3: Integration
- **#754** - Update server.py to register split route modules
  - Import all 10 new routers
  - Update background task imports
  - Test server startup

## Phase 4: Cleanup
- **#755** - Remove/deprecate original claims.py
  - Delete 2,873-line file
  - Update test imports
  - Final validation

## Issue Links
- Original issue: #735
- Foundation PR: #736
- Meta-issue: #756
- Module issues: #744-753
- Integration: #754
- Cleanup: #755

## Progress Tracking

Use the meta-issue (#756) to track overall progress. Each module issue is independent and can be worked on in parallel (except for #754 and #755 which depend on all modules being complete).

## Testing Strategy

Each module issue includes:
- Specific test commands
- Expected test coverage
- Integration points to verify

After all modules are created, run full test suite:
```bash
MOCK_DB_PATH=data/mock_db.json .venv/bin/pytest tests/ -v \
  --ignore=tests/integration --ignore=tests/e2e --ignore=tests/load \
  -m "not slow and not integration and not llm and not e2e and not load"
```
