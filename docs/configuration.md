# Configuration

This document describes all configuration options for the Agentic Claim Representative system.

For database configuration, see [Database](database.md). For getting started, see [Getting Started](getting-started.md).

## Environment Variables

All configuration is done through environment variables. Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
```

### Required

| Variable | Description | Example |
|----------|-------------|---------|
| `OPENAI_API_KEY` | API key for LLM provider (OpenRouter/OpenAI) | `sk-or-v1-...` |

### Optional

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENAI_API_BASE` | (none) | Custom API base URL (for OpenRouter) |
| `OPENAI_MODEL_NAME` | `gpt-4o-mini` | Model to use for agents |
| `CLAIMS_DB_PATH` | `data/claims.db` | Path to SQLite database |
| `MOCK_DB_PATH` | `data/mock_db.json` | Path to mock policy/vehicle data |
| `CA_COMPLIANCE_PATH` | `data/california_auto_compliance.json` | Path to CA compliance data |

## LLM Configuration

### Using OpenRouter

[OpenRouter](https://openrouter.ai/) provides access to multiple LLMs through a single API.

```bash
# .env
OPENAI_API_KEY=sk-or-v1-your-key-here
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=anthropic/claude-3-sonnet
```

Available models on OpenRouter:
- `anthropic/claude-3-opus`
- `anthropic/claude-3-sonnet`
- `openai/gpt-4-turbo`
- `openai/gpt-4o-mini`
- `meta-llama/llama-3-70b-instruct`

### Using OpenAI Directly

```bash
# .env
OPENAI_API_KEY=sk-your-openai-key
# Leave OPENAI_API_BASE empty for default OpenAI endpoint
OPENAI_MODEL_NAME=gpt-4o-mini
```

### Using Other OpenAI-Compatible APIs

Any OpenAI-compatible API can be used:

```bash
# .env
OPENAI_API_KEY=your-api-key
OPENAI_API_BASE=https://your-provider.com/v1
OPENAI_MODEL_NAME=your-model-name
```

## LLM Configuration Code

```python
# src/claim_agent/config/llm.py

def get_llm():
    """Return the configured LLM for agents."""
    from crewai import LLM
    
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable is required")
    
    base = os.environ.get("OPENAI_API_BASE", "").strip()
    model = os.environ.get("OPENAI_MODEL_NAME", "gpt-4o-mini").strip()
    
    if base and "openrouter" in base.lower():
        return LLM(model=model, base_url=base, api_key=api_key)
    return LLM(model=model, api_key=api_key)
```

## Data Files

### mock_db.json

Contains mock data for:
- **Policies**: Policy validation, coverage types, deductibles
- **Vehicle values**: Mock KBB-style valuations
- **claims**: Optional; reference/seed data only (often empty `[]`)

```json
{
  "policies": [
    {
      "policy_number": "POL-001",
      "status": "active",
      "coverage": "comprehensive",
      "deductible": 500
    }
  ],
  "vehicle_values": [
    {
      "vin": "1HGBH41JXMN109186",
      "value": 25000,
      "condition": "good"
    }
  ],
  "claims": []
}
```

### california_auto_compliance.json

California-specific compliance rules, deadlines, and disclosures:

```json
{
  "rules": [
    {
      "id": "CA-001",
      "category": "disclosure",
      "title": "Settlement Disclosure",
      "description": "Must disclose basis for settlement offer",
      "deadline_days": 30
    }
  ]
}
```

### State Policy Language Files

Reference policy language for different states:
- `california_auto_policy_language.json`
- `florida_auto_policy_language.json`
- `new_york_auto_policy_language.json`
- `texas_auto_policy_language.json`

## Agent Configuration

Agent roles, goals, and backstories are defined in **skill files** - markdown documents in the `skills/` folder. This allows easy customization of agent behavior without modifying code.

See [Skills](skills.md) for complete documentation.

### Skills Directory

```
src/claim_agent/skills/
├── router.md           # Claim Router Supervisor
├── intake.md           # Intake Specialist
├── policy_checker.md   # Policy Verification Specialist
└── ...                 # 20 skill files total
```

### Skill File Format

```markdown
# Router Agent Skill

## Role
Claim Router Supervisor

## Goal
Classify claims and delegate to appropriate workflow

## Backstory
Senior claims manager with expertise in routing
```

### Reference YAML Files

The `config/` folder also contains reference YAML files for agent and task definitions:

#### agents.yaml

```yaml
router:
  role: Claim Router Supervisor
  goal: Classify claims and delegate to appropriate workflow
  backstory: Senior claims manager with expertise in routing
```

#### tasks.yaml

```yaml
classify:
  description: Classify the claim as new, duplicate, total_loss, fraud, or partial_loss
  expected_output: One classification with brief reasoning
```

Note: Agents now load their configuration from skill files, which provide more detailed prompts and context than the YAML reference files.

## Directory Structure

```
project/
├── .env                    # Your configuration (not in git)
├── .env.example            # Template for .env
├── data/
│   ├── claims.db           # SQLite database (created automatically)
│   ├── mock_db.json        # Policy and vehicle data
│   ├── california_auto_compliance.json
│   └── *_auto_policy_language.json
└── src/claim_agent/
    ├── config/
    │   ├── llm.py          # LLM configuration
    │   ├── agents.yaml     # Agent reference
    │   └── tasks.yaml      # Task reference
    └── skills/
        ├── __init__.py     # Skill loading utilities
        └── *.md            # Agent skill definitions
```

## Logging

CrewAI logs are verbose by default. To reduce logging:

```python
import logging
logging.getLogger("crewai").setLevel(logging.WARNING)
```

## Testing Configuration

For testing without an API key:

```bash
# Run unit tests (no API key needed)
MOCK_DB_PATH=data/mock_db.json pytest tests/test_tools.py -v

# Run integration tests (API key required)
OPENAI_API_KEY=your-key pytest tests/test_crews.py -v
```

## Production Considerations

### Database

For production, consider:
1. Moving to PostgreSQL for better concurrency
2. Setting up regular backups
3. Implementing connection pooling

### API Keys

1. Use a secrets manager (AWS Secrets Manager, HashiCorp Vault)
2. Rotate keys regularly
3. Set up usage limits and monitoring

### Logging

1. Configure structured logging (JSON format)
2. Send logs to centralized logging service
3. Set up alerting for errors

### Performance

1. Consider caching for frequently accessed data
2. Use async processing for high-volume scenarios
3. Monitor LLM API usage and costs

## Configuration Validation

The system validates configuration at startup:

```python
# Fails fast if OPENAI_API_KEY is not set
from claim_agent.config.llm import get_llm
llm = get_llm()  # Raises ValueError if key missing
```

## Example .env File

```bash
# LLM Configuration (Required)
OPENAI_API_KEY=sk-or-v1-your-openrouter-key

# OpenRouter Configuration (Optional - for using OpenRouter)
OPENAI_API_BASE=https://openrouter.ai/api/v1
OPENAI_MODEL_NAME=anthropic/claude-3-sonnet

# Data Paths (Optional - defaults shown)
CLAIMS_DB_PATH=data/claims.db
MOCK_DB_PATH=data/mock_db.json
CA_COMPLIANCE_PATH=data/california_auto_compliance.json
```
