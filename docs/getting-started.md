# Getting Started

This guide walks you through setting up and running the Agentic Claim Representative system.

## Prerequisites

- Python 3.10 or higher
- API key from [OpenRouter](https://openrouter.ai/) or OpenAI

## Installation

### 1. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -e ".[dev]"
```

### 3. Configure Environment

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

Output shape (values depend on your DB and duplicate data in `data/mock_db.json`; use `new_claim.json` or a fresh `data/claims.db` for a simpler first run):

```json
{
  "claim_id": "CLM-…",
  "claim_type": "…",
  "router_output": "…",
  "workflow_output": "…",
  "summary": "…"
}
```

Processing a claim through the CLI calls a real LLM via `OPENAI_API_KEY` (placeholders such as `your_openrouter_key` are rejected). To explore the codebase **without** an API key, run the **test suite** (it mocks the LLM). `MOCK_CREW_ENABLED=true` simulates claimants, vision, and similar integrations—it does **not** replace the workflow LLM (see [Mock Crew Design](mock-crew-design.md)).

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
| `tests/sample_claims/new_claim.json` | new | First-time submission |
| `tests/sample_claims/partial_loss_parking.json` | partial_loss | Parking lot fender bender |
| `tests/sample_claims/duplicate_claim.json` | duplicate | Potential duplicate |
| `tests/sample_claims/total_loss_claim.json` | total_loss | Flood damage |
| `tests/sample_claims/fraud_claim.json` | fraud | Suspicious indicators |
| `tests/sample_claims/partial_loss_claim.json` | partial_loss | Repairable damage |
| `tests/sample_claims/partial_loss_fender.json` | partial_loss | Fender damage |
| `tests/sample_claims/partial_loss_front_collision.json` | partial_loss | Front collision |
| `tests/sample_claims/bodily_injury_claim.json` | bodily_injury | Bodily injury (BI workflow) |
| `tests/sample_claims/reopened_claim.json` | reopened | Prior settled claim reopened |
| `tests/sample_claims/coverage_denied_theft.json` | (workflow) | Coverage denied (theft) |
| `tests/sample_claims/territory_denied_mexico.json` | (workflow) | Territory / jurisdiction |
| `tests/sample_claims/multi_vehicle_incident.json` | (workflow) | Multi-vehicle / incident grouping |

See [Claim Types](claim-types.md) for classification criteria.

## Processing Different Claim Types

```bash
# New claim (explicit new-claim fixture)
claim-agent process tests/sample_claims/new_claim.json

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
pytest tests/ -v --ignore=tests/integration --ignore=tests/e2e --ignore=tests/load \
  -m "not slow and not integration and not llm and not e2e and not load"

# Integration tests (mocked LLM, no API key needed)
pytest tests/integration/ -v -m "integration and not slow and not llm"

# E2E tests (API + mocked LLM)
pytest tests/e2e/ -v -m e2e
```

## CLI Reference

| Command | Description |
|---------|-------------|
| `claim-agent process <file> [--attachment <file> ...]` | Process claim from JSON (optionally attach files) |
| `claim-agent status <id>` | Get claim status |
| `claim-agent history <id>` | Get audit log |
| `claim-agent reprocess <id> [--from-stage <stage>]` | Re-run workflow (optionally resume from a stage: `coverage_verification`, `economic_analysis`, `fraud_prescreening`, `duplicate_detection`, `router`, `escalation_check`, `workflow`, `task_creation`, `rental`, `liability_determination`, `settlement`, `subrogation`, `salvage`, `after_action`) |
| `claim-agent metrics [id]` | Show metrics (optional claim ID) |
| `claim-agent retention-enforce [--dry-run] [--years N] [--include-litigation-hold]` | Archive claims older than retention |
| `claim-agent document-retention-enforce [--dry-run] [--as-of YYYY-MM-DD]` | Soft-archive documents past `retention_date` |
| `claim-agent retention-purge …` / `retention-export …` / `audit-log-export …` / `audit-log-purge …` | Advanced retention and audit lifecycle (see [PII and Retention](pii-and-retention.md)) |
| `claim-agent retention-report [--years N] [--purge-years N] …` | Retention audit report |

See [docs/index.md](index.md) for the full CLI reference.

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
