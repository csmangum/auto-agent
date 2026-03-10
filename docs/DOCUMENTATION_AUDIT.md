# Documentation Audit Report

*Audit completed: March 2026*

## Summary

A comprehensive audit of the Agentic Claim Representative documentation was performed. Several issues were identified and fixed. This report summarizes the findings and changes made.

## Issues Found and Fixed

### 1. Missing File: design-considerations.md

**Issue:** The file `docs/design-considerations.md` was referenced in multiple places but did not exist:
- `docs/index.md` (Core Concepts)
- `docs/architecture.md` (footer)
- `docs/agent-flow.md` (Router Classification section)
- `README.md` (Documentation table)
- `src/claim_agent/api/routes/docs.py` (docs API)

**Fix:** Created `docs/design-considerations.md` with sections on:
- Router Classification (confidence threshold, optional validation)
- Known Limitations (data, workflow, observability)
- Future Enhancements

### 2. Incorrect Installation Step: "cd auto-agent"

**Issue:** `docs/getting-started.md` instructed users to `cd auto-agent`, which is not the project directory.

**Fix:** Removed the erroneous step. Users run setup from the project root.

### 3. Incorrect Final Status in claim-types.md

**Issue:** The Overview table listed incorrect final statuses:
- `total_loss`: documented as `closed`, actual is `settled` (set by Settlement Crew)
- `partial_loss`: documented as `partial_loss`, actual is `settled` (set by Settlement Crew)

**Fix:** Updated both to `settled` and added Settlement Crew reference.

### 4. Missing Sample Claim: bodily_injury_claim.json

**Issue:** `tests/sample_claims/bodily_injury_claim.json` exists but was not listed in sample claim tables.

**Fix:** Added to sample claims tables in `README.md` and `docs/getting-started.md`.

### 5. Incomplete Skills Documentation

**Issue:** `docs/skills.md` listed only core workflow skills. Many skills for sub-workflows (Rental, Salvage, Subrogation, Supplemental, Denial, Dispute, Bodily Injury, Reopened, Human Review Handback) were missing.

**Fix:** Updated Skills Directory with full list and added "Additional Workflows" section mapping skills to crews.

### 6. Outdated Test Instructions in getting-started.md

**Issue:** Test section said "Integration tests (API key required)" and referenced `tests/test_crews.py`.

**Fix:** Updated to match README: unit tests with proper pytest markers, integration tests with mocked LLM (no API key).

### 7. Missing Docs in Index and API

**Issue:** `docs/index.md` did not link to adjuster-workflow, review-queue, alerting, evaluation-results, compliance-corpus-requirements. The docs API did not include these pages.

**Fix:** Added "Human-in-the-Loop and Operations" section to index. Added missing pages to `_DOC_PAGES` in docs API.

## Verification

- All documentation files referenced in the index now exist.
- design-considerations.md is linked from agent-flow.md with correct anchor.
- CLI commands in index and README match `main.py` (serve, process, status, history, reprocess, metrics, review-queue, assign, approve, reject, request-info, escalate-siu, retention-enforce).
- Sample claims table includes all JSON files in `tests/sample_claims/`.
- Skills list matches `src/claim_agent/skills/*.md` (excluding README.md).

## Recommendations

1. **Keep design-considerations.md updated** when adding new limitations or future work.
2. **Add new sample claims to tables** when creating new test fixtures.
3. **Update skills.md** when adding new agent skills.
4. **Run link checker** periodically (e.g., `markdown-link-check`) to catch broken internal links.
