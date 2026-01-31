# Getting Started

This guide walks you through setting up and running the Agentic Claim Representative system.

## Prerequisites

- Python 3.10 or higher
- An API key from [OpenRouter](https://openrouter.ai/) or OpenAI

## Installation

### 1. Clone and Enter the Project

```bash
cd auto-agent
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -e ".[dev]"
```

This installs:
- `crewai` - Multi-agent framework
- `litellm` - LLM abstraction layer
- `pydantic` - Data validation
- `python-dotenv` - Environment management
- `mcp` - Model Context Protocol (optional)
- `pytest` - Testing (dev dependency)

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your API key:

```bash
# Required
OPENAI_API_KEY=sk-or-v1-your-openrouter-key

# For OpenRouter
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=anthropic/claude-3-sonnet

# Optional paths (defaults shown)
CLAIMS_DB_PATH=data/claims.db
MOCK_DB_PATH=data/mock_db.json
```

## Quick Start

### Process Your First Claim

```bash
claim-agent process tests/sample_claims/new_claim.json
```

Output:
```json
{
  "claim_id": "CLM-11EEF959",
  "claim_type": "new",
  "router_output": "new\nThis claim appears to be a first-time submission...",
  "workflow_output": "Claim ID: CLM-11EEF959, Status: open, Summary: ...",
  "summary": "Claim ID: CLM-11EEF959, Status: open, Summary: ..."
}
```

### Check Claim Status

```bash
claim-agent status CLM-11EEF959
```

### View Claim History

```bash
claim-agent history CLM-11EEF959
```

## Sample Claims

The project includes sample claims for testing:

| File | Type | Description |
|------|------|-------------|
| `tests/sample_claims/new_claim.json` | new | Standard first-time claim |
| `tests/sample_claims/duplicate_claim.json` | duplicate | Potential duplicate |
| `tests/sample_claims/total_loss_claim.json` | total_loss | Flood damage |
| `tests/sample_claims/fraud_claim.json` | fraud | Suspicious indicators |
| `tests/sample_claims/partial_loss_claim.json` | partial_loss | Repairable damage |
| `tests/sample_claims/partial_loss_fender.json` | partial_loss | Fender damage |
| `tests/sample_claims/partial_loss_front_collision.json` | partial_loss | Front collision |

## Example: Processing Different Claim Types

### New Claim

```bash
claim-agent process tests/sample_claims/new_claim.json
```

The system will:
1. Classify as "new"
2. Validate all fields
3. Verify policy
4. Assign claim ID
5. Set status to "open"

### Total Loss Claim

```bash
claim-agent process tests/sample_claims/total_loss_claim.json
```

The system will:
1. Classify as "total_loss"
2. Assess damage severity
3. Fetch vehicle value
4. Calculate payout
5. Generate settlement report

### Fraud Claim

```bash
claim-agent process tests/sample_claims/fraud_claim.json
```

The system will:
1. Classify as "fraud"
2. Analyze patterns
3. Cross-reference indicators
4. Generate fraud assessment
5. Recommend SIU referral if needed

### Partial Loss Claim

```bash
claim-agent process tests/sample_claims/partial_loss_claim.json
```

The system will:
1. Classify as "partial_loss"
2. Assess repairable damage
3. Calculate repair estimate
4. Assign repair shop
5. Order parts
6. Generate repair authorization

## Setting Up Duplicate Detection

To test duplicate detection, first seed historical claims:

```bash
python scripts/seed_claims_from_mock_db.py
```

Then process a duplicate claim:

```bash
claim-agent process tests/sample_claims/duplicate_claim.json
```

## Running Tests

```bash
# Unit tests (no API key needed)
export MOCK_DB_PATH=data/mock_db.json
pytest tests/ -v

# Specific test files
pytest tests/test_tools.py -v
pytest tests/test_db.py -v

# Integration tests (API key required)
pytest tests/test_crews.py -v
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `claim-agent process <file>` | Process a claim from JSON file |
| `claim-agent status <id>` | Get claim status |
| `claim-agent history <id>` | Get claim audit log |
| `claim-agent reprocess <id>` | Re-run workflow for existing claim |
| `claim-agent <file>` | Legacy: same as process |

## Next Steps

1. **[Architecture](architecture.md)** - Understand the system design
2. **[Claim Types](claim-types.md)** - Learn about different claim workflows
3. **[Tools](tools.md)** - Explore available tools
4. **[Configuration](configuration.md)** - Advanced configuration options

## Troubleshooting

### "OPENAI_API_KEY environment variable is required"

Ensure your `.env` file exists and contains a valid API key:
```bash
cat .env | grep OPENAI_API_KEY
```

### "File not found" errors

Ensure you're in the project root directory:
```bash
ls data/mock_db.json  # Should exist
```

### LLM errors

Check your API key is valid and has credits:
```bash
# Test with curl (OpenRouter)
curl https://openrouter.ai/api/v1/models \
  -H "Authorization: Bearer $OPENAI_API_KEY"
```

### Database errors

Reset the database:
```bash
rm data/claims.db
# Will be recreated on next use
```

## Creating a Custom Claim

Create a JSON file with required fields:

```json
{
  "policy_number": "POL-001",
  "vin": "1HGBH41JXMN109186",
  "vehicle_year": 2022,
  "vehicle_make": "Honda",
  "vehicle_model": "Accord",
  "incident_date": "2025-01-28",
  "incident_description": "Describe what happened",
  "damage_description": "Describe the damage",
  "estimated_damage": 5000
}
```

Process it:
```bash
claim-agent process my_claim.json
```
