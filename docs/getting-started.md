# Getting Started

This guide walks you through setting up and running the Agentic Claim Representative system.

## Prerequisites

- Python 3.10 or higher
- API key from [OpenRouter](https://openrouter.ai/) or OpenAI

## Installation

### 1. Enter the Project

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

### 4. Configure Environment

```bash
cp .env.example .env
```

Edit `.env`:

```bash
OPENAI_API_KEY=sk-or-v1-your-openrouter-key
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=anthropic/claude-3-sonnet
```

See [Configuration](configuration.md) for all options.

## Quick Start

### Process Your First Claim

```bash
claim-agent process tests/sample_claims/partial_loss_parking.json
```

Output:
```json
{
  "claim_id": "CLM-11EEF959",
  "claim_type": "new",
  "router_output": "new\nThis claim appears to be a first-time submission...",
  "workflow_output": "Claim ID: CLM-11EEF959, Status: open...",
  "summary": "Claim ID: CLM-11EEF959, Status: open..."
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

| File | Type | Description |
|------|------|-------------|
| `partial_loss_parking.json` | partial_loss | Parking lot fender bender |
| `duplicate_claim.json` | duplicate | Potential duplicate |
| `total_loss_claim.json` | total_loss | Flood damage |
| `fraud_claim.json` | fraud | Suspicious indicators |
| `partial_loss_claim.json` | partial_loss | Repairable damage |
| `partial_loss_fender.json` | partial_loss | Fender damage |
| `partial_loss_front_collision.json` | partial_loss | Front collision |

See [Claim Types](claim-types.md) for classification criteria.

## Processing Different Claim Types

```bash
# New claim
claim-agent process tests/sample_claims/partial_loss_parking.json

# Total loss
claim-agent process tests/sample_claims/total_loss_claim.json

# Fraud
claim-agent process tests/sample_claims/fraud_claim.json

# Partial loss
claim-agent process tests/sample_claims/partial_loss_claim.json
```

See [Crews](crews.md) for what each workflow does.

## Duplicate Detection Setup

To test duplicate detection, first seed historical claims:

```bash
python scripts/seed_claims_from_mock_db.py
```

Then:

```bash
claim-agent process tests/sample_claims/duplicate_claim.json
```

## Running Tests

```bash
# Unit tests (no API key needed)
export MOCK_DB_PATH=data/mock_db.json
pytest tests/ -v

# Integration tests (API key required)
pytest tests/test_crews.py -v
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `claim-agent process <file>` | Process claim from JSON |
| `claim-agent status <id>` | Get claim status |
| `claim-agent history <id>` | Get audit log |
| `claim-agent reprocess <id>` | Re-run workflow |

## Creating a Custom Claim

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

See [Claim Types - Required Fields](claim-types.md#required-fields).

## Troubleshooting

### "OPENAI_API_KEY environment variable is required"

Check your `.env` file:
```bash
cat .env | grep OPENAI_API_KEY
```

### "File not found" errors

Ensure you're in the project root:
```bash
ls data/mock_db.json
```

### Database errors

Reset the database:
```bash
rm data/claims.db
```

See [Database](database.md) for more details.

## Next Steps

1. **[Architecture](architecture.md)** - System design
2. **[Claim Types](claim-types.md)** - Classification criteria
3. **[Crews](crews.md)** - Workflow details
4. **[Tools](tools.md)** - Available tools
5. **[Configuration](configuration.md)** - Advanced options
