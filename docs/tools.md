# Tools Reference

Tools are the capabilities available to agents for accomplishing their tasks. Each tool wraps an implementation function and is decorated with CrewAI's `@tool` decorator.

## Tool Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TOOL ARCHITECTURE                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌───────────────────┐     ┌───────────────────┐     ┌──────────────────┐   │
│  │   CrewAI Tool     │────▶│  Implementation   │────▶│   Data Source    │   │
│  │   (@tool)         │     │  (*_impl)         │     │                  │   │
│  │                   │     │                   │     │  - SQLite        │   │
│  │  policy_tools.py  │     │  logic.py         │     │  - mock_db.json  │   │
│  │  claims_tools.py  │     │                   │     │  - compliance    │   │
│  │  valuation_tools  │     │                   │     │                  │   │
│  │  ...              │     │                   │     │                  │   │
│  └───────────────────┘     └───────────────────┘     └──────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Tool Categories

| Category | File | Tools |
|----------|------|-------|
| Policy | `policy_tools.py` | query_policy_db |
| Claims | `claims_tools.py` | search_claims_db, compute_similarity |
| Valuation | `valuation_tools.py` | fetch_vehicle_value, evaluate_damage, calculate_payout |
| Document | `document_tools.py` | generate_report, generate_claim_id |
| Escalation | `escalation_tools.py` | evaluate_escalation, detect_fraud_indicators, generate_escalation_report |
| Fraud | `fraud_tools.py` | analyze_claim_patterns, cross_reference_fraud_indicators, perform_fraud_assessment, generate_fraud_report |
| Partial Loss | `partial_loss_tools.py` | get_available_repair_shops, assign_repair_shop, get_parts_catalog, create_parts_order, calculate_repair_estimate, generate_repair_authorization |
| Compliance | `compliance_tools.py` | search_california_compliance |

---

## Policy Tools

### query_policy_db

Query the policy database to validate policy and retrieve coverage details.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `policy_number` | string | The insurance policy number to look up |

**Returns:** JSON string
```json
{
  "valid": true,
  "coverage": "comprehensive",
  "deductible": 500,
  "message": "Policy is active"
}
```

**Usage by Agents:**
- Policy Verification Specialist (New Claim Crew)
- Payout Calculator (Total Loss Crew)

---

## Claims Tools

### search_claims_db

Search existing claims by VIN and incident date for potential duplicates.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `vin` | string | Vehicle identification number |
| `incident_date` | string | Date of incident (YYYY-MM-DD) |

**Returns:** JSON array
```json
[
  {
    "claim_id": "CLM-12345678",
    "vin": "1HGBH41JXMN109186",
    "incident_date": "2025-01-10",
    "incident_description": "Rear-ended at stoplight"
  }
]
```

**Usage by Agents:**
- Claims Search Specialist (Duplicate Crew)

---

### compute_similarity

Compare two incident descriptions and return a similarity score.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `description_a` | string | First incident description |
| `description_b` | string | Second incident description |

**Returns:** JSON string
```json
{
  "similarity_score": 85.5,
  "is_duplicate": true
}
```

**Threshold:** Score > 80% indicates likely duplicate

**Usage by Agents:**
- Similarity Analyst (Duplicate Crew)

---

## Valuation Tools

### fetch_vehicle_value

Fetch current market value for a vehicle (mock KBB API).

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `vin` | string | Vehicle identification number |
| `year` | integer | Year of vehicle |
| `make` | string | Vehicle manufacturer |
| `model` | string | Vehicle model |

**Returns:** JSON string
```json
{
  "value": 25000.00,
  "condition": "good",
  "source": "mock_kbb"
}
```

**Usage by Agents:**
- Vehicle Valuation Specialist (Total Loss Crew)
- Partial Loss Damage Assessor (Partial Loss Crew)

---

### evaluate_damage

Evaluate damage description and optional repair cost to assess severity.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `damage_description` | string | Text description of vehicle damage |
| `estimated_repair_cost` | float (optional) | Estimated repair cost in dollars |

**Returns:** JSON string
```json
{
  "severity": "moderate",
  "estimated_repair_cost": 5000.00,
  "total_loss_candidate": false
}
```

**Severity Levels:**
- `minor`: Scratches, small dents
- `moderate`: Bumper, fender, lights
- `severe`: Multiple panels, frame
- `total_loss`: Unrepairable

**Usage by Agents:**
- Damage Assessor (Total Loss Crew)
- Partial Loss Damage Assessor (Partial Loss Crew)

---

### calculate_payout

Calculate total loss payout by subtracting policy deductible from vehicle value.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `vehicle_value` | float | Current market value of the vehicle |
| `policy_number` | string | Policy number to look up deductible |

**Returns:** JSON string
```json
{
  "payout_amount": 24000.00,
  "vehicle_value": 25000.00,
  "deductible": 1000.00,
  "calculation": "25000.00 - 1000.00 = 24000.00"
}
```

**Usage by Agents:**
- Payout Calculator (Total Loss Crew)

---

## Document Tools

### generate_report

Generate a claim report/summary document.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_id` | string | The claim ID |
| `claim_type` | string | Type of claim (new, duplicate, etc.) |
| `status` | string | Claim status (open, closed, etc.) |
| `summary` | string | Summary of actions taken |
| `payout_amount` | float (optional) | Settlement amount if applicable |

**Returns:** Formatted report string

**Usage by Agents:**
- Claim Assignment Specialist (New Claim Crew)
- Settlement Specialist (Total Loss Crew)
- Repair Authorization Specialist (Partial Loss Crew)

---

### generate_claim_id

Generate a unique claim ID.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `prefix` | string (default: "CLM") | Prefix for the claim ID |

**Returns:** Claim ID string (e.g., `CLM-11EEF959`)

**Usage by Agents:**
- Claim Assignment Specialist (New Claim Crew)
- Settlement Specialist (Total Loss Crew)

---

## Escalation Tools

### evaluate_escalation

Evaluate whether a claim needs human review.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_data` | string | JSON string of claim input |
| `router_output` | string | Raw text output from router |
| `similarity_score` | string (optional) | Numeric string (0-100) |
| `payout_amount` | string (optional) | Numeric string for payout |

**Returns:** JSON string
```json
{
  "needs_review": true,
  "escalation_reasons": ["high_value", "fraud_indicators"],
  "priority": "high",
  "fraud_indicators": ["staged_accident_language"],
  "recommended_action": "Review with fraud team"
}
```

**Escalation Triggers:**
- Fraud indicators detected
- Payout amount > $25,000
- Low router confidence
- Ambiguous similarity (60-80%)

---

### detect_fraud_indicators

Check claim data for fraud indicators.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_data` | string | JSON string of claim input |

**Returns:** JSON array of fraud indicator strings
```json
["staged_accident_keywords", "inflated_damage_estimate"]
```

---

### generate_escalation_report

Format an escalation result as a human-readable report.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_id` | string | Claim ID |
| `needs_review` | string | "true" or "false" |
| `escalation_reasons` | string | JSON array of reasons |
| `priority` | string | low, medium, high, critical |
| `recommended_action` | string | Action text |
| `fraud_indicators` | string (optional) | JSON array of indicators |

**Returns:** Formatted report string

---

## Fraud Tools

### analyze_claim_patterns

Analyze claim for suspicious patterns.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_data` | string | JSON string of claim input |
| `vin` | string (optional) | VIN to analyze if not in claim_data |

**Returns:** JSON string
```json
{
  "patterns_detected": ["multiple_claims_90_days"],
  "timing_flags": ["new_policy_quick_claim"],
  "claim_history": [...],
  "risk_factors": ["staged_accident_indicator"],
  "pattern_score": 65
}
```

**Patterns Detected:**
- Multiple claims on same VIN within 90 days
- Suspicious timing (new policy, quick filing)
- Staged accident indicators
- Claim frequency anomalies

---

### cross_reference_fraud_indicators

Cross-reference claim against known fraud indicators database.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_data` | string | JSON string of claim input |

**Returns:** JSON string
```json
{
  "fraud_keywords_found": ["staged", "inflated"],
  "database_matches": [...],
  "risk_level": "high",
  "cross_reference_score": 75,
  "recommendations": ["Refer to SIU"]
}
```

---

### perform_fraud_assessment

Perform comprehensive fraud assessment.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_data` | string | JSON string of claim input |
| `pattern_analysis` | string (optional) | JSON from analyze_claim_patterns |
| `cross_reference` | string (optional) | JSON from cross_reference_fraud_indicators |

**Returns:** JSON string
```json
{
  "fraud_score": 72,
  "fraud_likelihood": "high",
  "fraud_indicators": ["staged_accident", "inflated_estimate"],
  "recommended_action": "Refer to Special Investigations Unit",
  "should_block": false,
  "siu_referral": true
}
```

---

### generate_fraud_report

Generate a human-readable fraud assessment report.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_id` | string | Claim ID |
| `fraud_likelihood` | string | low, medium, high, critical |
| `fraud_score` | string | Numeric score as string |
| `fraud_indicators` | string | JSON array of indicators |
| `recommended_action` | string | Action text |
| `siu_referral` | string (optional) | "true" or "false" |
| `should_block` | string (optional) | "true" or "false" |

**Returns:** Formatted report string
```
============================================================
FRAUD ASSESSMENT REPORT — Claim CLM-12345678
============================================================

Fraud Likelihood: HIGH
Risk Score: 72

SIU Referral Required: YES
Claim Blocked: No

Fraud Indicators Detected:
  1. staged_accident
  2. inflated_estimate

Recommended Action:
  Refer to Special Investigations Unit

============================================================
```

---

## Partial Loss Tools

### get_available_repair_shops

Get list of available repair shops.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `location` | string (optional) | City/state filter |
| `vehicle_make` | string (optional) | Vehicle make for specialty matching |
| `network_type` | string (optional) | preferred, premium, standard |

**Returns:** JSON array
```json
{
  "shops": [
    {
      "shop_id": "SHOP-001",
      "name": "Quality Auto Body",
      "address": "123 Main St",
      "phone": "555-0100",
      "rating": 4.8,
      "network_type": "preferred",
      "wait_days": 2
    }
  ]
}
```

---

### assign_repair_shop

Assign a repair shop to a partial loss claim.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_id` | string | Claim ID |
| `shop_id` | string | Repair shop ID (e.g., SHOP-001) |
| `estimated_repair_days` | integer (default: 5) | Estimated days to complete |

**Returns:** JSON string
```json
{
  "success": true,
  "confirmation_number": "CONF-12345",
  "shop_id": "SHOP-001",
  "estimated_start_date": "2025-01-28",
  "estimated_completion_date": "2025-02-02"
}
```

---

### get_parts_catalog

Get recommended parts from catalog based on damage description.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `damage_description` | string | Description of damage |
| `vehicle_make` | string | Vehicle manufacturer |
| `part_type_preference` | string (default: "aftermarket") | oem, aftermarket, refurbished |

**Returns:** JSON string
```json
{
  "recommended_parts": [
    {
      "part_id": "PART-BUMPER-001",
      "name": "Rear Bumper Cover",
      "part_type": "aftermarket",
      "price": 350.00,
      "availability": "in_stock"
    }
  ],
  "total_parts_cost": 550.00
}
```

---

### create_parts_order

Create a parts order for a repair claim.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_id` | string | Claim ID |
| `parts` | list | List of dicts with part_id, quantity, part_type |
| `shop_id` | string (optional) | Shop ID for delivery |

**Returns:** JSON string
```json
{
  "order_id": "ORD-12345",
  "claim_id": "CLM-12345678",
  "parts": [...],
  "total_cost": 550.00,
  "estimated_delivery": "2025-01-30"
}
```

---

### calculate_repair_estimate

Calculate a complete repair estimate including parts and labor.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `damage_description` | string | Description of damage |
| `vehicle_make` | string | Vehicle manufacturer |
| `vehicle_year` | integer | Vehicle year |
| `policy_number` | string | Policy number for deductible lookup |
| `shop_id` | string (optional) | Shop ID for labor rate |
| `part_type_preference` | string (default: "aftermarket") | oem, aftermarket, refurbished |

**Returns:** JSON string
```json
{
  "parts_cost": 550.00,
  "labor_hours": 4.5,
  "labor_rate": 75.00,
  "labor_cost": 337.50,
  "total_estimate": 887.50,
  "deductible": 500.00,
  "customer_pays": 500.00,
  "insurance_pays": 387.50
}
```

---

### generate_repair_authorization

Generate a repair authorization document.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `claim_id` | string | Claim ID |
| `shop_id` | string | Assigned repair shop ID |
| `total_estimate` | float | Total repair estimate |
| `parts_cost` | float | Authorized parts cost |
| `labor_cost` | float | Authorized labor cost |
| `deductible` | float | Policy deductible |
| `customer_pays` | float | Customer responsibility |
| `insurance_pays` | float | Insurance payment |
| `customer_approved` | boolean (default: true) | Customer approval status |

**Returns:** JSON string
```json
{
  "authorization_id": "AUTH-12345",
  "claim_id": "CLM-12345678",
  "shop_id": "SHOP-001",
  "authorized_amount": 887.50,
  "terms": "Work must be completed within 30 days",
  "status": "authorized"
}
```

---

## Compliance Tools

### search_california_compliance

Search California auto insurance compliance/regulatory reference data.

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `query` | string (optional) | Keyword to search for |

**Returns:** JSON string with matching compliance entries

**Data Source:** `data/california_auto_compliance.json`

---

## Tool Implementation Pattern

All tools follow a consistent pattern:

```python
# In tools/<category>_tools.py
from crewai.tools import tool
from claim_agent.tools.logic import <tool>_impl

@tool("<Tool Name>")
def tool_function(param1: str, param2: int = 0) -> str:
    """Tool description for LLM.
    Args:
        param1: Description of param1.
        param2: Description of param2.
    Returns:
        JSON string with result.
    """
    return <tool>_impl(param1, param2)
```

```python
# In tools/logic.py
def <tool>_impl(param1: str, param2: int) -> str:
    """Core implementation logic."""
    # Business logic here
    return json.dumps(result)
```

This separation allows:
1. Tools to be used by CrewAI agents
2. Same logic to be exposed via MCP server
3. Direct testing of implementation without CrewAI
