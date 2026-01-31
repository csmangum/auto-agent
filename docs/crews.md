# Crews

Crews are collections of agents that work together to accomplish a specific workflow. Each crew is designed to handle a particular type of claim processing. This document details all crews in the system.

## Overview

| Crew | Purpose | Agents | Tasks |
|------|---------|--------|-------|
| Router Crew | Classify incoming claims | 1 | 1 |
| New Claim Crew | Process first-time claims | 3 | 3 |
| Duplicate Crew | Handle potential duplicates | 3 | 3 |
| Total Loss Crew | Process total loss claims | 4 | 4 |
| Fraud Detection Crew | Analyze suspicious claims | 3 | 3 |
| Partial Loss Crew | Handle repairable damage | 5 | 5 |

---

## Router Crew

**Location**: `src/claim_agent/crews/main_crew.py`

The Router Crew is the entry point for all claim processing. It contains a single agent that classifies claims.

### Agent

| Agent | Role | Goal |
|-------|------|------|
| Claim Router Supervisor | Classify claims | Route to appropriate workflow |

### Task Flow

```
┌──────────────────────────────────────┐
│         Classify Claim Task          │
│  - Analyze claim data                │
│  - Determine: new, duplicate,        │
│    total_loss, fraud, partial_loss   │
│  - Provide reasoning                 │
└──────────────────────────────────────┘
```

### Classification Criteria

| Type | Indicators |
|------|------------|
| `new` | First-time submission, no red flags |
| `duplicate` | Same VIN/date as existing claim |
| `total_loss` | Totaled, flood, fire, destroyed, frame damage |
| `fraud` | Staged accident, inflated estimates, suspicious patterns |
| `partial_loss` | Bumper, fender, door, dents, scratches, repairable |

---

## New Claim Crew

**Location**: `src/claim_agent/crews/new_claim_crew.py`

Handles first-time claim submissions through validation, policy verification, and assignment.

### Agents

| Agent | Role | Goal | Tools Used |
|-------|------|------|------------|
| Intake Specialist | Validate data | Ensure required fields present | - |
| Policy Verification Specialist | Check policy | Verify active coverage | `query_policy_db` |
| Claim Assignment Specialist | Assign claim | Generate ID and report | `generate_claim_id`, `generate_report` |

### Task Flow

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Validate Claim     │────▶│  Check Policy       │────▶│  Assign Claim       │
│                     │     │                     │     │                     │
│ - Required fields   │     │ - Query policy DB   │     │ - Generate claim ID │
│ - Data types        │     │ - Verify active     │     │ - Set status: open  │
│ - Formats           │     │ - Check coverage    │     │ - Generate report   │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

### Required Fields

- `policy_number`
- `vin`
- `vehicle_year`
- `vehicle_make`
- `vehicle_model`
- `incident_date`
- `incident_description`
- `damage_description`
- `estimated_damage` (optional)

---

## Duplicate Crew

**Location**: `src/claim_agent/crews/duplicate_crew.py`

Identifies and resolves potential duplicate claims.

### Agents

| Agent | Role | Goal | Tools Used |
|-------|------|------|------------|
| Claims Search Specialist | Find matches | Search existing claims | `search_claims_db` |
| Similarity Analyst | Compare claims | Compute similarity score | `compute_similarity` |
| Duplicate Resolution Specialist | Resolve | Decide merge/reject | - |

### Task Flow

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Search Claims      │────▶│  Compute Similarity │────▶│  Resolve Duplicate  │
│                     │     │                     │     │                     │
│ - Match VIN         │     │ - Compare desc.     │     │ - If >80%: merge    │
│ - Match date        │     │ - Score 0-100       │     │ - Else: reject      │
│ - Find candidates   │     │ - Flag if >80%      │     │ - Provide reasoning │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

### Similarity Threshold

- **>80%**: Likely duplicate, recommend merge
- **<80%**: Not duplicate, process normally

---

## Total Loss Crew

**Location**: `src/claim_agent/crews/total_loss_crew.py`

Processes claims where the vehicle is a total loss (unrepairable or repair cost exceeds value).

### Agents

| Agent | Role | Goal | Tools Used |
|-------|------|------|------------|
| Damage Assessor | Assess damage | Evaluate severity | `evaluate_damage` |
| Vehicle Valuation Specialist | Get value | Fetch market value | `fetch_vehicle_value` |
| Payout Calculator | Calculate | Compute settlement | `calculate_payout` |
| Settlement Specialist | Close claim | Generate report | `generate_claim_id`, `generate_report` |

### Task Flow

```
┌───────────────┐     ┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│ Assess Damage │────▶│ Get Valuation │────▶│ Calculate     │────▶│ Settlement    │
│               │     │               │     │ Payout        │     │               │
│ - Severity    │     │ - Market val  │     │ - Value       │     │ - Report      │
│ - Total loss? │     │ - Condition   │     │ - Deductible  │     │ - Close claim │
│ - Est. cost   │     │ - Source      │     │ - Net payout  │     │ - Payout amt  │
└───────────────┘     └───────────────┘     └───────────────┘     └───────────────┘
```

### Total Loss Indicators

- Keywords: totaled, flood, fire, destroyed, frame damage, rollover, submerged
- Repair cost > 75% of vehicle value

### Payout Calculation

```
Payout = Vehicle Market Value - Policy Deductible
```

---

## Fraud Detection Crew

**Location**: `src/claim_agent/crews/fraud_detection_crew.py`

Analyzes claims flagged for potential fraud. This crew runs directly without escalation check.

### Agents

| Agent | Role | Goal | Tools Used |
|-------|------|------|------------|
| Fraud Pattern Analysis Specialist | Find patterns | Detect suspicious patterns | `analyze_claim_patterns` |
| Fraud Cross-Reference Specialist | Match indicators | Check fraud database | `cross_reference_fraud_indicators`, `detect_fraud_indicators` |
| Fraud Assessment Specialist | Assess risk | Determine fraud likelihood | `perform_fraud_assessment`, `generate_fraud_report` |

### Task Flow

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  Pattern Analysis   │────▶│  Cross-Reference    │────▶│  Fraud Assessment   │
│                     │     │                     │     │                     │
│ - Multiple claims   │     │ - Fraud keywords    │     │ - Overall score     │
│ - Timing anomalies  │     │ - Database matches  │     │ - Likelihood level  │
│ - Staged indicators │     │ - Prior flags       │     │ - SIU referral      │
│ - Risk factors      │     │ - Risk level        │     │ - Block decision    │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
```

### Fraud Indicators Detected

**Pattern Analysis:**
- Multiple claims on same VIN within 90 days
- Suspicious timing (new policy, quick filing)
- Staged accident indicators (multiple occupants, witnesses left)
- Claim frequency anomalies

**Cross-Reference:**
- Keywords: staged, inflated, pre-existing, phantom
- Damage estimate vs. vehicle value mismatch
- Prior fraud flags on VIN or policy

### Fraud Likelihood Levels

| Level | Score | Action |
|-------|-------|--------|
| Low | 0-25 | Process normally |
| Medium | 26-50 | Flag for review |
| High | 51-75 | SIU referral |
| Critical | 76-100 | Block claim |

---

## Partial Loss Crew

**Location**: `src/claim_agent/crews/partial_loss_crew.py`

Handles claims for repairable vehicle damage.

### Agents

| Agent | Role | Goal | Tools Used |
|-------|------|------|------------|
| Partial Loss Damage Assessor | Assess | Confirm repairability | `evaluate_damage`, `fetch_vehicle_value` |
| Repair Estimator | Estimate | Calculate repair costs | `calculate_repair_estimate`, `get_parts_catalog` |
| Repair Shop Coordinator | Assign shop | Find and assign shop | `get_available_repair_shops`, `assign_repair_shop` |
| Parts Ordering Specialist | Order parts | Create parts order | `get_parts_catalog`, `create_parts_order` |
| Repair Authorization Specialist | Authorize | Generate authorization | `generate_repair_authorization`, `generate_report` |

### Task Flow

```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│   Assess    │──▶│  Estimate   │──▶│   Assign    │──▶│   Order     │──▶│  Authorize  │
│   Damage    │   │   Repair    │   │    Shop     │   │   Parts     │   │   Repair    │
│             │   │             │   │             │   │             │   │             │
│ - Severity  │   │ - Parts $   │   │ - Find shop │   │ - Catalog   │   │ - Auth doc  │
│ - Parts     │   │ - Labor $   │   │ - Best fit  │   │ - Order     │   │ - Finalize  │
│ - Value     │   │ - Total     │   │ - Schedule  │   │ - Delivery  │   │ - Report    │
└─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘   └─────────────┘
```

### Damage Severity Levels

| Severity | Repair Days | Examples |
|----------|-------------|----------|
| Minor | 3 days | Scratches, dents, mirrors |
| Moderate | 5 days | Bumper, fender, lights |
| Severe | 7 days | Door, hood, frame work |

### Repair Estimate Breakdown

```
Total Estimate = Parts Cost + Labor Cost
Customer Pays  = Deductible (or Total if < Deductible)
Insurance Pays = Total Estimate - Customer Pays
```

---

## Creating a Custom Crew

To add a new claim type workflow:

1. **Create agents** in `src/claim_agent/agents/your_type.py`:
```python
from crewai import Agent

def create_your_agent(llm=None):
    return Agent(
        role="Your Role",
        goal="Your goal description",
        backstory="Agent backstory",
        llm=llm,
    )
```

2. **Create crew** in `src/claim_agent/crews/your_type_crew.py`:
```python
from crewai import Crew, Task
from claim_agent.config.llm import get_llm

def create_your_crew(llm=None):
    llm = llm or get_llm()
    agent = create_your_agent(llm)
    
    task = Task(
        description="Task description",
        expected_output="Expected output",
        agent=agent,
    )
    
    return Crew(
        agents=[agent],
        tasks=[task],
        verbose=True,
    )
```

3. **Register in main_crew.py**:
```python
# Add to run_claim_workflow()
elif claim_type == "your_type":
    crew = create_your_crew(llm)
```

4. **Update router classification** to recognize the new type.
