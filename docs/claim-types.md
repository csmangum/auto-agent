# Claim Types

The system supports five distinct claim types, each handled by a specialized workflow crew.

For crew details and agent composition, see [Crews](crews.md).

## Overview

| Type | Description | Final Status | Crew |
|------|-------------|--------------|------|
| `new` | First-time submission | `open` | [New Claim](crews.md#new-claim-crew) |
| `duplicate` | Duplicate of existing | `duplicate` | [Duplicate](crews.md#duplicate-crew) |
| `total_loss` | Unrepairable vehicle | `settled` | [Total Loss](crews.md#total-loss-crew) → [Settlement](crews.md#settlement-crew) |
| `fraud` | Suspected fraud | `fraud_suspected` | [Fraud](crews.md#fraud-detection-crew) |
| `partial_loss` | Repairable damage | `settled` | [Partial Loss](crews.md#partial-loss-crew) → [Settlement](crews.md#settlement-crew) |

---

## Classification Decision Tree

```mermaid
flowchart TD
    A[New Claim] --> B{Fraud indicators?}
    B -->|Yes| C[FRAUD]
    B -->|No| D{Same VIN/date exists?}
    D -->|Yes| E[DUPLICATE]
    D -->|No| F{Total loss keywords?}
    F -->|Yes| G[TOTAL_LOSS]
    F -->|No| H{Repair > 75% value?}
    H -->|Yes| G
    H -->|No| I{Repairable damage?}
    I -->|Yes| J[PARTIAL_LOSS]
    I -->|No| K[NEW]
```

---

## New Claim

Standard first-time claim submissions with no red flags. For the formal workflow specification (entry conditions, flow sequence, acceptance criteria), see [New Claim Crew](crews.md#new-claim-crew).

### Classification Criteria

- First-time submission for this incident
- No duplicate indicators (different VIN or date)
- No fraud indicators in description
- Damage not clearly total or partial loss

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `policy_number` | string | Insurance policy number |
| `vin` | string | Vehicle identification number |
| `vehicle_year` | integer | Year of vehicle |
| `vehicle_make` | string | Vehicle manufacturer |
| `vehicle_model` | string | Vehicle model |
| `incident_date` | string (YYYY-MM-DD) | Date of incident; validated as date by Pydantic |
| `incident_description` | string | Description of the incident |
| `damage_description` | string | Description of vehicle damage |
| `estimated_damage` | float | Estimated repair cost (optional) |

### Example

```json
{
  "policy_number": "POL-001",
  "vin": "1HGBH41JXMN109186",
  "vehicle_year": 2021,
  "vehicle_make": "Honda",
  "vehicle_model": "Accord",
  "incident_date": "2025-01-15",
  "incident_description": "Rear-ended at stop light",
  "damage_description": "Minor rear bumper damage",
  "estimated_damage": 2500
}
```

---

## Duplicate Claim

Claims matching existing claims in the system. For the formal workflow specification (entry conditions, flow sequence, acceptance criteria), see [Duplicate Crew](crews.md#duplicate-crew).

### Classification Criteria

- Same VIN as an existing claim
- Same or similar incident date
- Similar incident description

### Similarity Thresholds

| Score | Interpretation | Action |
|-------|----------------|--------|
| 0-50 | Low similarity | Not duplicate, process normally |
| 51-79 | Moderate | Review recommended (may escalate) |
| 80-100 | High similarity | Likely duplicate, recommend merge/reject |

### Example

```json
{
  "policy_number": "POL-001",
  "vin": "1HGBH41JXMN109186",
  "incident_date": "2025-01-10",
  "incident_description": "Rear-ended at intersection on Main St",
  "damage_description": "Bumper and taillight damage"
}
```

---

## Total Loss

Vehicle is unrepairable or repair cost exceeds value. For the formal workflow specification (entry conditions, flow sequence, acceptance criteria), see [Total Loss Crew](crews.md#total-loss-crew).

### Classification Criteria

**Keywords:** totaled, flood, submerged, fire, burned, destroyed, frame damage, rollover

**Cost-based:** Repair cost > 75% of vehicle value

### Payout Formula

```
Payout = Vehicle Market Value - Policy Deductible

Example: $25,000 value - $1,000 deductible = $24,000 payout
```

### Example

```json
{
  "policy_number": "POL-002",
  "vin": "5YJSA1DN1CFP01234",
  "vehicle_year": 2020,
  "vehicle_make": "Tesla",
  "vehicle_model": "Model 3",
  "incident_date": "2025-01-20",
  "incident_description": "Flash flood while parked in underground garage",
  "damage_description": "Vehicle submerged for 3 hours. Electrical systems damaged.",
  "estimated_damage": 45000
}
```

---

## Fraud

Claims with indicators suggesting fraudulent activity. For the formal workflow specification (entry conditions, flow sequence, acceptance criteria), see [Fraud Detection Crew](crews.md#fraud-detection-crew).

### Classification Criteria

**Staged Accident Indicators:**
- "staged accident" language
- Multiple occupants with vague details
- Witnesses who "left the scene"
- Inconsistent damage vs. description

**Financial Red Flags:**
- Inflated damage estimates
- Prior fraud history on VIN/policy
- Damage estimate >> vehicle value

**Pattern Anomalies:**
- Multiple claims within 90 days
- New policy with quick filing

### Fraud Likelihood Levels

| Level | Score | Action |
|-------|-------|--------|
| Low | 0-25 | Process normally |
| Medium | 26-50 | Flag for review |
| High | 51-75 | Refer to SIU |
| Critical | 76-100 | Block claim |

### Example

```json
{
  "policy_number": "POL-FRAUD-001",
  "vin": "3VWDX7AJ5DM999999",
  "vehicle_year": 2019,
  "vehicle_make": "Volkswagen",
  "vehicle_model": "Jetta",
  "incident_date": "2025-01-22",
  "incident_description": "Staged accident. Multiple occupants complained of whiplash.",
  "damage_description": "Front bumper destroyed. Engine, transmission, frame damage.",
  "estimated_damage": 35000
}
```

---

## Partial Loss

Repairable vehicle damage. For the formal workflow specification (entry conditions, flow sequence, acceptance criteria), see [Partial Loss Crew](crews.md#partial-loss-crew).

### Classification Criteria

**Keywords:** bumper, fender, door, mirror, light, windshield, dent, scratch, crack

**Cost:** Typically < $10,000, repair cost < 75% of vehicle value

### Damage Severity → Repair Days

| Severity | Repair Days | Examples |
|----------|-------------|----------|
| Minor | 3 days | Scratches, dents, mirrors |
| Moderate | 5 days | Bumper, fender, lights |
| Severe | 7 days | Door, hood, multiple panels |

### Cost Breakdown

```
Total = Parts Cost + Labor Cost
Customer Pays = Deductible (or Total if Total < Deductible)
Insurance Pays = Total - Customer Pays
```

### Part Types

| Type | Description | Cost |
|------|-------------|------|
| OEM | Original manufacturer | Higher |
| Aftermarket | Third-party | Lower |
| Refurbished | Reconditioned | Lowest |

### Supplemental (Sub-Workflow)

When additional damage is discovered during repair, the [Supplemental Crew](crews.md#supplemental-crew) handles it as a sub-workflow. Invoke via `POST /claims/{claim_id}/supplemental` with:

```json
{
  "supplemental_damage_description": "Hidden frame damage discovered during bumper removal",
  "reported_by": "shop"
}
```

Allowed claim statuses: `processing`, `settled`. California CCR 2695.8 requires prompt inspection and authorization.

### Example

```json
{
  "policy_number": "POL-003",
  "vin": "2T1BURHE5JC073987",
  "vehicle_year": 2022,
  "vehicle_make": "Toyota",
  "vehicle_model": "Corolla",
  "incident_date": "2025-01-25",
  "incident_description": "Backed into pole in parking lot",
  "damage_description": "Rear bumper cracked, taillight broken",
  "estimated_damage": 1800
}
```

---

## Sample Claims

The project includes sample claims for testing in `tests/sample_claims/`:

| File | Type |
|------|------|
| `new_claim.json` | new |
| `partial_loss_parking.json` | partial_loss |
| `duplicate_claim.json` | duplicate |
| `total_loss_claim.json` | total_loss |
| `fraud_claim.json` | fraud |
| `partial_loss_claim.json` | partial_loss |
| `partial_loss_fender.json` | partial_loss |
| `partial_loss_front_collision.json` | partial_loss |

See [Getting Started](getting-started.md#sample-claims) for usage.
