# Agent Flow

This document describes the execution flow of the claim processing system, from initial claim submission to final output.

## High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CLAIM PROCESSING FLOW                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  1. INPUT                                                                    │
│     ├── CLI: claim-agent process <claim.json>                               │
│     └── Parsed as ClaimInput (Pydantic validation)                          │
│                                                                              │
│  2. INITIALIZATION                                                           │
│     ├── Create claim record in SQLite                                       │
│     ├── Generate claim ID (CLM-XXXXXXXX)                                    │
│     └── Set status: pending → processing                                    │
│                                                                              │
│  3. CLASSIFICATION (Router Crew)                                             │
│     ├── Router agent analyzes claim data                                    │
│     └── Returns: new | duplicate | total_loss | fraud | partial_loss        │
│                                                                              │
│  4. ESCALATION CHECK (HITL)                                                  │
│     ├── Skip if claim_type == fraud                                         │
│     ├── Check: fraud indicators, high value, low confidence                 │
│     └── If needs_review → return early with escalation details              │
│                                                                              │
│  5. WORKFLOW EXECUTION                                                       │
│     ├── Select crew based on claim_type                                     │
│     ├── Run crew with claim_data                                            │
│     └── Get workflow output                                                 │
│                                                                              │
│  6. FINALIZATION                                                             │
│     ├── Save workflow result to database                                    │
│     ├── Update claim status to final status                                 │
│     └── Return JSON response                                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Detailed Execution Flow

### Step 1: Input Validation

```python
# CLI Entry (main.py)
claim-agent process tests/sample_claims/new_claim.json

# Validation (using Pydantic)
from claim_agent.models.claim import ClaimInput
ClaimInput.model_validate(claim_data)
```

The system validates:
- All required fields are present
- Data types are correct
- Formats are valid (e.g., incident_date as YYYY-MM-DD)

### Step 2: Claim Initialization

```python
# Create claim in database
repo = ClaimRepository()
claim_id = repo.create_claim(claim_input)  # Returns CLM-XXXXXXXX

# Update status
repo.update_claim_status(claim_id, STATUS_PROCESSING)
```

**Database Operations:**
1. Insert new claim record
2. Create audit log entry (`action: created`)
3. Update status with audit log entry (`action: status_changed`)

### Step 3: Classification (Router Crew)

```
┌────────────────────────────────────────────────────────┐
│                    ROUTER CREW                          │
├────────────────────────────────────────────────────────┤
│                                                         │
│  Agent: Claim Router Supervisor                         │
│                                                         │
│  Input: claim_data (JSON)                               │
│                                                         │
│  Task: Classify claim as one of:                        │
│    - new: First-time submission                         │
│    - duplicate: Possible duplicate                      │
│    - total_loss: Vehicle destroyed                      │
│    - fraud: Fraud indicators present                    │
│    - partial_loss: Repairable damage                    │
│                                                         │
│  Output: "<type>\n<reasoning>"                          │
│    Example: "partial_loss\nBumper damage is repairable" │
│                                                         │
└────────────────────────────────────────────────────────┘
```

**Classification Logic:**
1. Router agent receives claim_data as JSON
2. Analyzes incident_description and damage_description
3. Checks for keywords and patterns
4. Returns one-word classification with reasoning

### Step 4: Escalation Check (HITL)

```
┌────────────────────────────────────────────────────────┐
│                  ESCALATION CHECK                       │
├────────────────────────────────────────────────────────┤
│                                                         │
│  Skip if: claim_type == "fraud"                         │
│    (Fraud crew handles its own assessment)              │
│                                                         │
│  Evaluate:                                              │
│    ├── Fraud indicators in descriptions                 │
│    ├── High payout amount (> $25,000)                  │
│    ├── Low router confidence                            │
│    └── Ambiguous similarity score (60-80%)              │
│                                                         │
│  If needs_review == true:                               │
│    ├── Set status: needs_review                         │
│    ├── Save escalation reasons                          │
│    ├── Set priority (low/medium/high/critical)          │
│    └── Return early (skip workflow crew)                │
│                                                         │
└────────────────────────────────────────────────────────┘
```

**Escalation Criteria:**

| Criteria | Condition | Priority |
|----------|-----------|----------|
| Fraud indicators | Keywords detected | high |
| High value | Payout > $25,000 | high |
| Low confidence | Router unsure | medium |
| Ambiguous duplicate | 60-80% similarity | medium |

### Step 5: Workflow Execution

Based on `claim_type`, the appropriate crew is selected:

```python
if claim_type == "new":
    crew = create_new_claim_crew(llm)
elif claim_type == "duplicate":
    crew = create_duplicate_crew(llm)
elif claim_type == "fraud":
    crew = create_fraud_detection_crew(llm)
elif claim_type == "partial_loss":
    crew = create_partial_loss_crew(llm)
else:  # total_loss
    crew = create_total_loss_crew(llm)

workflow_result = crew.kickoff(inputs={"claim_data": json.dumps(claim_data)})
```

**Crew Execution:**
1. Crew receives `claim_data` as input
2. Tasks execute sequentially (with context passing)
3. Each agent uses tools to accomplish its task
4. Final task output becomes workflow_output

### Step 6: Finalization

```python
# Save workflow result
repo.save_workflow_result(claim_id, claim_type, router_output, workflow_output)

# Update final status
final_status = _final_status(claim_type)
repo.update_claim_status(claim_id, final_status, details=workflow_output)
```

**Status Mapping:**

| Claim Type | Final Status |
|------------|--------------|
| new | open |
| duplicate | duplicate |
| total_loss | closed |
| fraud | fraud_suspected |
| partial_loss | partial_loss |

## Agent Communication

Agents communicate through **task context**. Each task can receive context from previous tasks:

```python
# Example from duplicate_crew.py
search_task = Task(
    description="Search existing claims...",
    agent=search_agent,
)

similarity_task = Task(
    description="Compare descriptions...",
    agent=similarity_agent,
    context=[search_task],  # Receives output from search_task
)

resolve_task = Task(
    description="Decide merge/reject...",
    agent=resolution_agent,
    context=[search_task, similarity_task],  # Receives both outputs
)
```

## Tool Usage Flow

Agents use tools to accomplish tasks:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           TOOL USAGE FLOW                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. Agent receives task description                                      │
│                                                                          │
│  2. Agent determines which tool(s) to use                                │
│                                                                          │
│  3. Agent calls tool with parameters                                     │
│     └── Tool: @tool decorator (CrewAI)                                   │
│         └── Implementation: _impl function (logic.py)                    │
│             └── Data source: SQLite / mock_db.json                       │
│                                                                          │
│  4. Tool returns JSON result                                             │
│                                                                          │
│  5. Agent interprets result and continues                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Example: Policy Verification**

```
Agent: Policy Verification Specialist
Task: Verify policy is active

Step 1: Agent calls query_policy_db("POL-001")
Step 2: Tool queries mock_db.json
Step 3: Returns: {"valid": true, "coverage": "comprehensive", "deductible": 500}
Step 4: Agent reports: "Policy POL-001 is active with comprehensive coverage"
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        ERROR HANDLING FLOW                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  try:                                                                    │
│      # Normal processing flow                                            │
│      result = run_claim_workflow(claim_data)                             │
│                                                                          │
│  except Exception as e:                                                  │
│      # On any error:                                                     │
│      ├── Update claim status to "failed"                                 │
│      ├── Log error details (first 500 chars)                            │
│      └── Re-raise exception                                              │
│                                                                          │
│  Database state after error:                                             │
│      claims.status = "failed"                                            │
│      claim_audit_log = {action: "status_changed", new_status: "failed"}  │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Reprocessing Flow

Existing claims can be reprocessed:

```
claim-agent reprocess CLM-11EEF959

┌─────────────────────────────────────────────────────────────────────────┐
│                        REPROCESS FLOW                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. Fetch existing claim from database                                   │
│                                                                          │
│  2. Rebuild claim_data from stored fields                                │
│                                                                          │
│  3. Validate with ClaimInput                                             │
│                                                                          │
│  4. Run workflow with existing_claim_id                                  │
│     (uses same claim ID, doesn't create new)                             │
│                                                                          │
│  5. Update claim with new workflow result                                │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Output Format

### Successful Processing (Not Escalated)

```json
{
  "claim_id": "CLM-11EEF959",
  "claim_type": "new",
  "router_output": "new\nThis claim appears to be a first-time submission...",
  "workflow_output": "Claim ID: CLM-11EEF959, Status: open, Summary: ...",
  "summary": "Claim ID: CLM-11EEF959, Status: open, Summary: ..."
}
```

### Escalated (Needs Review)

```json
{
  "claim_id": "CLM-11EEF959",
  "claim_type": "new",
  "status": "needs_review",
  "router_output": "new\n...",
  "workflow_output": "{\"escalation_reasons\": [\"high_value\"], ...}",
  "summary": "Escalated for review: high_value",
  "escalation_reasons": ["high_value"],
  "priority": "high",
  "needs_review": true,
  "recommended_action": "Review payout amount.",
  "fraud_indicators": []
}
```

## Sequence Diagram

```
┌─────┐    ┌─────────┐    ┌──────────┐    ┌────────────┐    ┌──────────┐
│ CLI │    │ main.py │    │ Database │    │ Router     │    │ Workflow │
│     │    │         │    │          │    │ Crew       │    │ Crew     │
└──┬──┘    └────┬────┘    └────┬─────┘    └─────┬──────┘    └────┬─────┘
   │            │              │                │                 │
   │ process    │              │                │                 │
   │ claim.json │              │                │                 │
   │───────────▶│              │                │                 │
   │            │              │                │                 │
   │            │ validate     │                │                 │
   │            │─────────────▶│                │                 │
   │            │              │                │                 │
   │            │ create_claim │                │                 │
   │            │─────────────▶│                │                 │
   │            │◀─────────────│                │                 │
   │            │ claim_id     │                │                 │
   │            │              │                │                 │
   │            │ kickoff(claim_data)           │                 │
   │            │──────────────────────────────▶│                 │
   │            │◀──────────────────────────────│                 │
   │            │ claim_type                    │                 │
   │            │              │                │                 │
   │            │ escalation   │                │                 │
   │            │ check        │                │                 │
   │            │─────────────▶│                │                 │
   │            │              │                │                 │
   │            │ kickoff(claim_data)                             │
   │            │────────────────────────────────────────────────▶│
   │            │◀────────────────────────────────────────────────│
   │            │ workflow_output                                 │
   │            │              │                │                 │
   │            │ save_result  │                │                 │
   │            │─────────────▶│                │                 │
   │            │              │                │                 │
   │◀───────────│              │                │                 │
   │ JSON output│              │                │                 │
   │            │              │                │                 │
```
