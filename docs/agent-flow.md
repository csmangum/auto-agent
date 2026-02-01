# Agent Flow

This document describes the execution flow of the claim processing system, from input to output.

For crew details, see [Crews](crews.md). For claim classification, see [Claim Types](claim-types.md).

## High-Level Flow

```mermaid
flowchart TB
    subgraph Input
        A[CLI: claim-agent process]
        B[Pydantic Validation]
    end
    
    subgraph Init["Initialization"]
        C[Create claim in SQLite]
        D[Generate CLM-ID]
        E[Status: pending → processing]
    end
    
    subgraph Classification
        F[Router Crew]
        G{claim_type}
    end
    
    subgraph Escalation["Escalation Check"]
        H{Fraud type?}
        I[Evaluate escalation]
        J{needs_review?}
    end
    
    subgraph Workflow
        K[Select Crew]
        L[Execute Tasks]
    end
    
    subgraph Finalize
        M[Save Result]
        N[Update Status]
        O[Return JSON]
    end
    
    A --> B --> C --> D --> E --> F --> G --> H
    H -->|Yes| K
    H -->|No| I --> J
    J -->|Yes| O
    J -->|No| K --> L --> M --> N --> O
```

## Step-by-Step Execution

### 1. Input Validation

```python
claim-agent process tests/sample_claims/partial_loss_parking.json

# Validates with Pydantic
from claim_agent.models.claim import ClaimInput
ClaimInput.model_validate(claim_data)
```

See [Claim Types - Required Fields](claim-types.md#required-fields) for field requirements.

### 2. Claim Initialization

```python
repo = ClaimRepository()
claim_id = repo.create_claim(claim_input)  # Returns CLM-XXXXXXXX
repo.update_claim_status(claim_id, STATUS_PROCESSING)
```

Creates audit log entries. See [Database](database.md) for schema.

### 3. Classification (Router Crew)

```mermaid
flowchart LR
    A[claim_data JSON] --> B[Router Agent]
    B --> C[Analyze descriptions]
    C --> D[Return type + reasoning]
```

Output: `"partial_loss\nBumper damage is repairable"`

### 4. Escalation Check (HITL)

**Skipped for fraud claims** (fraud crew does its own assessment).

```mermaid
flowchart TD
    A[Evaluate] --> B{Fraud indicators?}
    A --> C{Payout > $25k?}
    A --> D{Low confidence?}
    A --> E{Similarity 60-80%?}
    
    B -->|Yes| F[needs_review = true]
    C -->|Yes| F
    D -->|Yes| F
    E -->|Yes| F
```

| Criteria | Priority |
|----------|----------|
| Fraud indicators | high |
| High value (>$25k) | high |
| Low confidence | medium |
| Ambiguous similarity | medium |

### 5. Workflow Execution

```python
if claim_type == "new":
    crew = create_new_claim_crew(llm)
elif claim_type == "duplicate":
    crew = create_duplicate_crew(llm)
elif claim_type == "fraud":
    crew = create_fraud_detection_crew(llm)
elif claim_type == "partial_loss":
    crew = create_partial_loss_crew(llm)
else:
    crew = create_total_loss_crew(llm)

workflow_result = crew.kickoff(inputs={"claim_data": json.dumps(claim_data)})
```

See [Crews](crews.md) for crew details.

### 6. Finalization

```python
repo.save_workflow_result(claim_id, claim_type, router_output, workflow_output)
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

Agents communicate through **task context**:

```python
search_task = Task(description="Search claims...", agent=search_agent)

similarity_task = Task(
    description="Compare descriptions...",
    agent=similarity_agent,
    context=[search_task],  # Receives search_task output
)

resolve_task = Task(
    description="Decide merge/reject...",
    agent=resolution_agent,
    context=[search_task, similarity_task],  # Receives both
)
```

## Tool Usage

```mermaid
flowchart LR
    A[Agent] --> B[Determine tool]
    B --> C["@tool decorator"]
    C --> D["_impl function"]
    D --> E[Data source]
    E --> F[JSON result]
    F --> A
```

See [Tools](tools.md) for complete tool reference.

## Error Handling

```mermaid
flowchart TD
    A[Processing] --> B{Error?}
    B -->|No| C[Success]
    B -->|Yes| D[Set status: failed]
    D --> E[Log error details]
    E --> F[Re-raise exception]
```

On error, the database records:
- `claims.status = "failed"`
- `claim_audit_log.new_status = "failed"`

## Reprocessing

```bash
claim-agent reprocess CLM-11EEF959
```

```mermaid
flowchart LR
    A[Fetch claim] --> B[Rebuild claim_data]
    B --> C[Validate]
    C --> D[Run workflow]
    D --> E[Update claim]
```

Uses same claim ID, doesn't create new record.

## Output Formats

### Successful (Not Escalated)

```json
{
  "claim_id": "CLM-11EEF959",
  "claim_type": "new",
  "router_output": "new\nFirst-time submission...",
  "workflow_output": "Claim ID: CLM-11EEF959, Status: open...",
  "summary": "Claim ID: CLM-11EEF959, Status: open..."
}
```

### Escalated (Needs Review)

```json
{
  "claim_id": "CLM-11EEF959",
  "claim_type": "new",
  "status": "needs_review",
  "escalation_reasons": ["high_value"],
  "priority": "high",
  "needs_review": true,
  "recommended_action": "Review payout amount.",
  "fraud_indicators": []
}
```

## Sequence Diagram

```mermaid
sequenceDiagram
    participant CLI
    participant Main as main.py
    participant DB as Database
    participant Router as Router Crew
    participant Workflow as Workflow Crew

    CLI->>Main: process claim.json
    Main->>DB: validate & create_claim
    DB-->>Main: claim_id
    Main->>Router: kickoff(claim_data)
    Router-->>Main: claim_type
    Main->>Main: escalation check
    Main->>Workflow: kickoff(claim_data)
    Workflow-->>Main: workflow_output
    Main->>DB: save_result
    Main-->>CLI: JSON output
```
