# Eval Suite: Remaining Gaps

This document tracks known gaps in the claim processing evaluation suite. Gaps that have been addressed are listed in the [Addressed Gaps (Reference)](#addressed-gaps-reference) section below.

**Last updated:** March 2025

---

## Addressed Gaps (Reference)

The following gaps were addressed in a prior audit:

- Missing `bodily_injury` and `reopened` claim types in eval scenarios
- `expected_status` not used in evaluation accuracy logic
- Fragile evaluation test imports (scripts path)
- Sample claims mapping incomplete (`new_claim.json`, `bodily_injury_claim.json`)
- Sample claim test mismatch with `SAMPLE_CLAIMS_MAPPING`
- Duplicate conftest fixtures between e2e and integration

The following gaps were addressed in March 2025:

- **Eval script not run in CI:** Added `eval` job (workflow_dispatch) that runs `evaluate_claim_processing.py --quick` with OPENAI_API_KEY from secrets; uploads report as artifact
- **No eval coverage for standalone workflows:** Added `scripts/evaluate_standalone_workflows.py` for supplemental, dispute, denial/coverage, and handback workflows (mocked LLMs); runs in unit CI
- **Load tests excluded from CI:** Added `load` job that runs `tests/load/` with LOAD_TEST_CONCURRENCY=2
- **LLM tests non-deterministic:** Documented expected variance via `LLM_ROUTER_VALID_OUTCOMES` in `test_workflow.py`; tests use bounded assertions
