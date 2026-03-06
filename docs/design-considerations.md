# Design Considerations

This document captures design tradeoffs, known limitations, and future considerations for the Agentic Claim Representative POC. For the main system design, see [Architecture](architecture.md).

## Router Classification

### Current Behavior

The router classifies claims into one of five types. There is no explicit confidence score from the LLM; instead, `claim_agent.tools.logic` uses `_parse_router_confidence()` to infer confidence from router output text. Keywords like "possibly", "unclear", "might be", "unsure", "could be", and "uncertain" reduce the inferred confidence. This feeds into the escalation check.

### Limitation

Misclassification sends the claim to the wrong crew. There is no re-routing, validation step, or fallback. If the router classifies a claim as `partial_loss` but it is actually fraud, the Partial Loss crew runs.

### Future Options

- Explicit confidence in router output (structured JSON)
- Confidence threshold for re-classification
- Lightweight validation step before workflow execution

## Escalation Scope

### Current Behavior

Escalation runs once, after classification and before any workflow. Criteria include:

- Low confidence (inferred from router output)
- High-value payout threshold
- Fraud indicators (keywords, multiple claims on same VIN, damage vs. vehicle value ratio, description mismatch)
- Ambiguous duplicate similarity scores

See [Escalation Tools](tools.md#escalation-tools) and `evaluate_escalation_impl` in `claim_agent.tools.logic`.

### Limitation

No mid-workflow escalation. If a crew discovers fraud or high risk during processing (e.g., Total Loss crew finds damage inconsistent with incident description), it completes the workflow and reports. There is no "pause and escalate" path.

### Future Options

- Allow crews to call an escalation tool mid-workflow
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
| Router     | Keyword-based confidence inference      | No explicit confidence; misclassification not recoverable |
| Escalation | Pre-workflow only                       | No mid-workflow escalation                                |
| Data       | SQLite (claims) + Mock JSON (reference) | Mock DB role not obvious from architecture diagram        |
| Reprocess  | Full re-run, append to workflow_runs    | No partial recovery or resume                             |


