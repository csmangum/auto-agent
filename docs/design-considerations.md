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

## Reprocessing and Checkpointing

### Behavior

`claim-agent reprocess <claim_id>` re-runs the workflow for an existing claim.
Each run is appended to `workflow_runs` and now also writes per-stage checkpoints
to the `task_checkpoints` table so that future reprocessing can resume from the
last successful stage.

### Checkpoint Schema

```
task_checkpoints
├── claim_id          TEXT NOT NULL  (FK → claims.id)
├── workflow_run_id   TEXT NOT NULL  (groups checkpoints for one execution)
├── stage_key         TEXT NOT NULL  (e.g. "router", "workflow:total_loss")
├── output            TEXT NOT NULL  (JSON-serialised stage output)
└── created_at        TEXT           (auto-populated)
UNIQUE(claim_id, workflow_run_id, stage_key)
```

### Stages

The workflow is divided into four checkpoint stages, executed in order:

| Stage key              | What is checkpointed |
| ---------------------- | -------------------- |
| `router`               | claim_type, confidence, reasoning, raw router output |
| `escalation_check`     | Result of pre-workflow escalation evaluation (only saved when not escalated) |
| `workflow:{claim_type}` | Primary crew output and extracted payout amount |
| `settlement`           | Settlement crew output (only for total_loss / partial_loss) |

### Resume Logic

When `resume_run_id` is passed to `run_claim_workflow`:

1. All checkpoints for `(claim_id, workflow_run_id)` are loaded.
2. If `from_stage` is also given, checkpoints at and after that stage are deleted.
3. For each stage, if a checkpoint exists the cached output is used; otherwise the stage runs normally and a checkpoint is written on success.
4. Failed stages are **not** checkpointed, so reprocessing naturally retries them.

### CLI

```
claim-agent reprocess <claim_id> --from-task <stage>
```

`--from-task` accepts one of: `router`, `escalation_check`, `workflow`, `settlement`.
The CLI looks up the most recent `workflow_run_id` with checkpoints and resumes
from the specified stage.

### API

```
POST /api/claims/{claim_id}/reprocess?from_stage=workflow
```

Optional `from_stage` query parameter; same semantics as the CLI flag.

## Summary


| Area       | Current                                 | Limitation                                                |
| ---------- | --------------------------------------- | --------------------------------------------------------- |
| Router     | Structured JSON (claim_type, confidence, reasoning); threshold + optional validation | — |
| Escalation | Pre-workflow + mid-workflow (escalate_claim tool) | — |
| Data       | SQLite (claims) + Mock JSON (reference) | Mock DB role not obvious from architecture diagram        |
| Reprocess  | Per-stage checkpoints; resume via `--from-task` / `from_stage` | Checkpoints are at stage boundaries, not individual CrewAI tasks |


