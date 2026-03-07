# Design Considerations

This document captures design tradeoffs, known limitations, and future considerations for the Agentic Claim Representative POC. For the main system design, see [Architecture](architecture.md).

## Router Classification

### Current Behavior

The router returns structured JSON with `claim_type`, `confidence` (0.0–1.0), and `reasoning` via `output_pydantic=RouterOutput`. Confidence is explicit from the LLM, not inferred from keywords. When the LLM returns non-JSON or legacy format, the system falls back to `_parse_claim_type()` and `_parse_router_confidence()` for backward compatibility.

**Confidence threshold:** `ROUTER_CONFIDENCE_THRESHOLD` (default 0.7). When confidence < threshold: escalate to `needs_review` for human classification (Option A).

**Optional validation:** `ROUTER_VALIDATION_ENABLED=true` runs a second LLM call. If validation returns confidence ≥ threshold, the workflow proceeds with the validated classification (re-classification if validation disagrees). If validation also returns low confidence, the claim is escalated.

### Misclassification Recovery

- **Original vs final classification:** When validation disagrees with the router, the `router_reclassified` event logs both. The workflow proceeds with the validated classification.
- **Escalation:** Low-confidence claims are escalated before any workflow runs, so misclassification does not send the claim to the wrong crew.

## Escalation Scope

### Current Behavior

Escalation runs once, after classification and before any workflow. Criteria include:

- Low confidence (inferred from router output)
- High-value payout threshold
- Fraud indicators (keywords, multiple claims on same VIN, damage vs. vehicle value ratio, description mismatch)
- Ambiguous duplicate similarity scores

See [Escalation Tools](tools.md#escalation-tools) and `evaluate_escalation_impl` in `claim_agent.tools.logic`.

### Mid-Workflow Escalation

Any workflow agent can call the `escalate_claim` tool during processing. When called, crew execution halts immediately, the claim status is set to `needs_review`, and the claim appears in the review queue. See [Agent Flow - Mid-Workflow Escalation](agent-flow.md#mid-workflow-escalation).

### Future Options

- Add a final review step that can flag for human review before closing

## Data Layer: SQLite vs Mock DB

The architecture diagram shows both "SQLite" and "Mock Data" in the Data Layer. They serve different purposes:


| Store       | Purpose                                                                                                                                                    | Location                                                                                                     |
| ----------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| **SQLite**  | Persistent storage for claims, audit logs, and workflow runs. Used for claim lifecycle, status, and reprocessing.                                          | `claim_agent.db.database`, `claim_agent.db.repository`; path via `CLAIMS_DB_PATH` (default `data/claims.db`) |
| **Mock DB** | JSON file containing reference data—policies, historical claims for lookup, vehicle values. Tools (policy lookup, valuation, fraud checks) read from this. | `claim_agent.tools.data_loader`; path via `MOCK_DB_PATH` (default `data/mock_db.json`)                       |


The Mock DB is not an alternative to SQLite; it is supplementary reference data for the POC. SQLite holds the claim record; Mock DB provides lookup data for tools.

## Reprocessing and Partial Failures

### Current Behavior

`claim-agent reprocess <claim_id>` loads the claim from SQLite and re-runs the full workflow (router + escalation + workflow crew). Each run is appended to `workflow_runs`. There is no checkpointing or resume from a specific task.

### Limitation

If a crew fails partway through (e.g., task 2 of 4 succeeds, task 3 times out), the claim remains in `processing` or an intermediate state. Reprocess starts from scratch—no partial state recovery. Idempotency is at the "full run" level, not per-task.

### Future Options

- Task-level checkpoints
- Idempotent task keys
- Explicit "retry from task N" for long workflows

## Summary


| Area       | Current                                 | Limitation                                                |
| ---------- | --------------------------------------- | --------------------------------------------------------- |
| Router     | Structured JSON (claim_type, confidence, reasoning); threshold + optional validation | — |
| Escalation | Pre-workflow + mid-workflow (escalate_claim tool) | — |
| Data       | SQLite (claims) + Mock JSON (reference) | Mock DB role not obvious from architecture diagram        |
| Reprocess  | Full re-run, append to workflow_runs    | No partial recovery or resume                             |


