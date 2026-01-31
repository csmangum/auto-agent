# Claim Types

The system supports five distinct claim types, each handled by a specialized workflow crew. This document describes each claim type, its classification criteria, and processing workflow.

## Overview

| Claim Type | Description | Final Status |
|------------|-------------|--------------|
| `new` | First-time claim submission | `open` |
| `duplicate` | Likely duplicate of existing claim | `duplicate` |
| `total_loss` | Vehicle is total loss (unrepairable) | `closed` |
| `fraud` | Suspected fraudulent claim | `fraud_suspected` |
| `partial_loss` | Repairable vehicle damage | `partial_loss` |

---

## New Claim

Standard first-time claim submissions with no red flags.

### Classification Criteria

- First-time submission for this incident
- No duplicate indicators (different VIN or date from existing claims)
- No fraud indicators in description
- Damage is not clearly total loss or partial loss

### Processing Workflow

1. **Intake Validation**
   - Verify all required fields present
   - Validate data types and formats

2. **Policy Verification**
   - Query policy database
   - Confirm policy is active
   - Verify coverage applies

3. **Claim Assignment**
   - Generate unique claim ID (format: `CLM-XXXXXXXX`)
   - Set status to `open`
   - Generate claim report

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `policy_number` | string | Insurance policy number |
| `vin` | string | Vehicle identification number |
| `vehicle_year` | integer | Year of vehicle |
| `vehicle_make` | string | Vehicle manufacturer |
| `vehicle_model` | string | Vehicle model |
| `incident_date` | string | Date of incident (YYYY-MM-DD) |
| `incident_description` | string | Description of the incident |
| `damage_description` | string | Description of vehicle damage |
| `estimated_damage` | float (optional) | Estimated repair cost in dollars |

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

Claims that appear to be duplicates of existing claims in the system.

### Classification Criteria

- Same VIN as an existing claim
- Same or similar incident date
- Similar incident description
- Already reported by the same policyholder

### Processing Workflow

1. **Claims Search**
   - Search by VIN and incident date
   - Find matching or similar claims

2. **Similarity Analysis**
   - Compare incident descriptions
   - Compute similarity score (0-100)
   - Flag if score > 80%

3. **Resolution**
   - **Merge**: If confirmed duplicate, merge with existing claim
   - **Reject**: If duplicate with conflicting data, reject

### Similarity Scoring

The system uses a text similarity algorithm to compare incident descriptions:

| Score Range | Interpretation | Action |
|-------------|----------------|--------|
| 0-50 | Low similarity | Process as new claim |
| 51-79 | Moderate similarity | Review recommended |
| 80-100 | High similarity | Likely duplicate |

### Example

```json
{
  "policy_number": "POL-001",
  "vin": "1HGBH41JXMN109186",
  "vehicle_year": 2021,
  "vehicle_make": "Honda",
  "vehicle_model": "Accord",
  "incident_date": "2025-01-10",
  "incident_description": "Rear-ended at intersection on Main St",
  "damage_description": "Bumper and taillight damage"
}
```
*If a claim with same VIN and date already exists, this will be classified as duplicate.*

---

## Total Loss

Claims where the vehicle is considered a total loss (unrepairable or repair cost exceeds value).

### Classification Criteria

**Keyword-based:**
- totaled, total loss
- flood, submerged
- fire, burned
- destroyed, demolished
- frame damage
- rollover

**Cost-based:**
- Repair cost > 75% of vehicle value
- Damage severity indicates unrepairable

### Processing Workflow

1. **Damage Assessment**
   - Evaluate damage description
   - Estimate repair cost
   - Confirm total loss status

2. **Vehicle Valuation**
   - Fetch market value (mock KBB API)
   - Determine condition and source

3. **Payout Calculation**
   - Get policy deductible
   - Calculate: `Payout = Value - Deductible`

4. **Settlement**
   - Generate settlement report
   - Close claim with payout amount

### Payout Formula

```
Payout Amount = Vehicle Market Value - Policy Deductible

Example:
- Vehicle Value: $25,000
- Deductible: $1,000
- Payout: $24,000
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
  "damage_description": "Vehicle submerged in water for 3 hours. Electrical systems damaged.",
  "estimated_damage": 45000
}
```

---

## Fraud

Claims with indicators suggesting fraudulent activity.

### Classification Criteria

**Staged Accident Indicators:**
- "staged accident" language
- Multiple occupants with vague details
- Witnesses who "left the scene"
- Inconsistent damage vs. description

**Financial Red Flags:**
- Inflated damage estimates
- Prior fraud history on VIN/policy
- Suspiciously high repair costs
- Damage estimate >> vehicle value

**Pattern Anomalies:**
- Multiple claims within 90 days
- New policy with quick claim filing
- Claim frequency anomalies

### Processing Workflow

1. **Pattern Analysis**
   - Check claim history on VIN
   - Analyze timing patterns
   - Detect staged accident indicators

2. **Cross-Reference**
   - Search fraud keyword database
   - Check prior fraud flags
   - Compare damage to value

3. **Fraud Assessment**
   - Combine pattern and cross-reference scores
   - Determine fraud likelihood level
   - Recommend action (SIU referral, block)

### Fraud Likelihood Levels

| Level | Score | Indicators | Action |
|-------|-------|------------|--------|
| Low | 0-25 | No significant indicators | Process normally |
| Medium | 26-50 | Some flags present | Flag for human review |
| High | 51-75 | Multiple strong indicators | Refer to SIU |
| Critical | 76-100 | Confirmed fraud patterns | Block claim |

### Example

```json
{
  "policy_number": "POL-FRAUD-001",
  "vin": "3VWDX7AJ5DM999999",
  "vehicle_year": 2019,
  "vehicle_make": "Volkswagen",
  "vehicle_model": "Jetta",
  "incident_date": "2025-01-22",
  "incident_description": "Staged accident with other vehicle. Multiple occupants complained of whiplash.",
  "damage_description": "Front bumper completely destroyed. Engine damage. Transmission damage. Frame bent.",
  "estimated_damage": 35000
}
```

---

## Partial Loss

Claims for repairable vehicle damage.

### Classification Criteria

**Damage Keywords:**
- Bumper, fender, door
- Mirror, light, windshield
- Dent, scratch, crack
- Minor collision, parking lot incident

**Cost Indicators:**
- Estimated damage typically < $10,000
- Repair cost < 75% of vehicle value

### Processing Workflow

1. **Damage Assessment**
   - Evaluate damage severity
   - List damaged components
   - Confirm repairability

2. **Repair Estimate**
   - Get parts from catalog
   - Calculate labor hours
   - Compute total cost

3. **Shop Assignment**
   - Find available shops
   - Select based on rating/availability
   - Assign and schedule

4. **Parts Ordering**
   - Match parts to damage
   - Create order (OEM/aftermarket)
   - Track delivery

5. **Repair Authorization**
   - Generate authorization document
   - Calculate customer vs. insurance responsibility
   - Finalize claim

### Damage Severity Levels

| Severity | Examples | Est. Repair Days |
|----------|----------|------------------|
| Minor | Scratches, small dents, mirrors | 3 days |
| Moderate | Bumper, fender, lights, windshield | 5 days |
| Severe | Door, hood, multiple panels | 7 days |

### Cost Breakdown

```
Total Estimate = Parts Cost + Labor Cost

Insurance Calculation:
- If Total > Deductible:
  - Customer Pays: Deductible
  - Insurance Pays: Total - Deductible
- If Total <= Deductible:
  - Customer Pays: Total
  - Insurance Pays: $0
```

### Part Type Options

| Type | Description | Cost |
|------|-------------|------|
| OEM | Original equipment manufacturer | Higher |
| Aftermarket | Third-party parts | Lower |
| Refurbished | Reconditioned parts | Lowest |

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

## Claim Type Decision Tree

```
                                    ┌──────────────┐
                                    │  New Claim   │
                                    └──────┬───────┘
                                           │
                                           ▼
                              ┌────────────────────────┐
                              │ Contains fraud         │
                              │ keywords/indicators?   │
                              └───────┬────────────────┘
                                      │
                         ┌────────────┴────────────┐
                         │ Yes                     │ No
                         ▼                         ▼
                    ┌─────────┐         ┌─────────────────────┐
                    │  FRAUD  │         │ Same VIN/date as    │
                    └─────────┘         │ existing claim?     │
                                        └──────────┬──────────┘
                                                   │
                                      ┌────────────┴────────────┐
                                      │ Yes                     │ No
                                      ▼                         ▼
                                 ┌───────────┐      ┌───────────────────────┐
                                 │ DUPLICATE │      │ Total loss keywords   │
                                 └───────────┘      │ or repair > 75% value?│
                                                    └───────────┬───────────┘
                                                                │
                                                   ┌────────────┴────────────┐
                                                   │ Yes                     │ No
                                                   ▼                         ▼
                                             ┌───────────┐         ┌─────────────────┐
                                             │TOTAL_LOSS │         │ Repairable      │
                                             └───────────┘         │ damage keywords?│
                                                                   └────────┬────────┘
                                                                            │
                                                               ┌────────────┴────────────┐
                                                               │ Yes                     │ No
                                                               ▼                         ▼
                                                        ┌──────────────┐          ┌─────────┐
                                                        │ PARTIAL_LOSS │          │   NEW   │
                                                        └──────────────┘          └─────────┘
```
