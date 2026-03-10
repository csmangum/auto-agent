# Eval Suite: Remaining Gaps

This document tracks known gaps in the claim processing evaluation suite. Gaps that have been addressed are listed in the [Addressed Gaps (Reference)](#addressed-gaps-reference) section below.

**Last updated:** March 2025

---

## Medium Priority

### 1. Eval script not run in CI

**Status:** Open

**Description:** The full evaluation script (`scripts/evaluate_claim_processing.py`) is not executed in CI. Unit tests for the eval module (`tests/test_evaluation.py`) run as part of the unit job, but the LLM-based evaluation that measures routing accuracy, latency, and cost is only run manually.

**Impact:** No automated regression tracking for eval metrics. Changes to routing or crews may degrade accuracy without detection.

**Recommendation:** Add a scheduled or manual CI job that runs `evaluate_claim_processing.py --quick` with an API key (e.g. from secrets). Store reports as artifacts and optionally compare against a baseline to fail on significant regressions.

---

## Low Priority

### 2. No eval coverage for standalone workflows

**Status:** Open

**Description:** The eval script only exercises `run_claim_workflow` (main intake). These workflows have no eval scenarios:

- `run_supplemental_workflow` (supplemental_orchestrator)
- `run_dispute_workflow` (dispute_orchestrator)
- `run_denial_coverage_workflow` (denial_coverage_orchestrator)
- `run_handback_workflow` (handback_orchestrator)

**Impact:** Post-intake workflows are not evaluated for correctness or performance.

**Recommendation:** Add a separate eval script or mode for supplemental, dispute, denial/coverage, and handback workflows. Consider a shared scenario format and report structure.

---

### 3. Load tests excluded from CI

**Status:** Open

**Description:** The CI unit job explicitly ignores `tests/load/`:

```yaml
--ignore=tests/load
```

Load tests (`tests/load/test_concurrent_claims.py`) are never run in CI.

**Impact:** Concurrent claim submission behavior and throughput are not validated on each run.

**Recommendation:** Add a separate CI job for load tests (e.g. with limited concurrency and timeout) or run them on a schedule. Ensure the job does not block normal PR merges.

---

### 4. LLM tests are non-deterministic

**Status:** Open

**Description:** Integration workflow tests with real LLMs (`tests/integration/test_workflow.py`, `TestWorkflowWithLLM`) accept multiple valid claim types per scenario. The router is non-deterministic and may classify conservatively (e.g. `total_loss` → `new`, `fraud` → `new` or escalation).

**Impact:** Weaker regression signal for routing behavior. Tests may pass even when accuracy degrades.

**Recommendation:** Where possible, use deterministic scenarios (structured prompts, mocks, or fixed seeds). Where non-determinism is unavoidable, document expected variance and use bounded assertions (e.g. "must be one of {new, total_loss}").

---

## Addressed Gaps (Reference)

The following gaps were addressed in a prior audit:

- Missing `bodily_injury` and `reopened` claim types in eval scenarios
- `expected_status` not used in evaluation accuracy logic
- Fragile evaluation test imports (scripts path)
- Sample claims mapping incomplete (`new_claim.json`, `bodily_injury_claim.json`)
- Sample claim test mismatch with `SAMPLE_CLAIMS_MAPPING`
- Duplicate conftest fixtures between e2e and integration
