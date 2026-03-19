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
| `CREWAI_VERBOSE` | `true` | CrewAI verbose mode (`true`/`false`) |
| `CLAIM_AGENT_MAX_TOKENS_PER_CLAIM` | `150000` | Max tokens per claim before stopping |
| `CLAIM_AGENT_MAX_LLM_CALLS_PER_CLAIM` | `50` | Max LLM API calls per claim |

### Authentication and RBAC

When `API_KEYS`, `CLAIMS_API_KEY`, or `JWT_SECRET` is set, all `/api/*` endpoints (except `/api/health`) require authentication.

| Variable | Description |
|---------|-------------|
| `API_KEYS` | Comma-separated `key:role` pairs, e.g. `sk-adj-xxx:adjuster,sk-sup-yyy:supervisor,sk-admin-zzz:admin` |
| `CLAIMS_API_KEY` | Single API key (backward compat). When set and `API_KEYS` unset, treated as admin role |
| `JWT_SECRET` | Secret for verifying JWT Bearer tokens. JWT payload should include `sub` (user id) and `role` |

**Roles**: `adjuster` (submit/view claims, docs), `supervisor` (all adjuster + reprocess, metrics), `admin` (all + config, system).

Pass credentials via `X-API-Key` header or `Authorization: Bearer <key>`.

### Adapter Backends

Each external-system adapter can be configured independently. See [Adapters](adapters.md) for full documentation.

| Variable | Default | Values | Description |
|----------|---------|--------|-------------|
| `POLICY_ADAPTER` | `mock` | `mock`, `stub` | Policy database backend |
| `VALUATION_ADAPTER` | `mock` | `mock`, `stub` | Vehicle valuation backend |
| `REPAIR_SHOP_ADAPTER` | `mock` | `mock`, `stub` | Repair shop network backend |
| `PARTS_ADAPTER` | `mock` | `mock`, `stub` | Parts catalog backend |
| `SIU_ADAPTER` | `mock` | `mock`, `stub` | SIU case management backend |
| `CLAIM_SEARCH_ADAPTER` | `mock` | `mock`, `stub` | Claim search backend (fraud cross-reference) |
| `SIU_DEFAULT_STATE` | `California` | Any state name | Fallback state for SIU fraud bureau reporting when claim/policy state is missing |
| `VISION_ADAPTER` | `real` | `real`, `mock` | Vision analysis: `real` (litellm) or `mock` (claim-context derived) |
| `OCR_ADAPTER` | `mock` | `mock`, `stub` | OCR for document extraction (estimates, photos) |

### Mock Crew (Testing)

The Mock Crew simulates external interactions for E2E testing without real people or services. See [Mock Crew Design](mock-crew-design.md).

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_CREW_ENABLED` | `false` | Enable Mock Crew (claimant, vision, etc.) |
| `MOCK_CREW_SEED` | (none) | Optional seed for reproducible mock outputs |
| `MOCK_IMAGE_GENERATOR_ENABLED` | `false` | Generate damage images via OpenRouter |
| `MOCK_IMAGE_MODEL` | `google/gemini-2.0-flash-exp` | OpenRouter model for image generation |
| `MOCK_IMAGE_VISION_ANALYSIS_SOURCE` | `claim_context` | Vision analysis: `claim_context` (mock) or `openrouter` (real API) |

### Observability

Logging, tracing, and metrics are configurable via: `CLAIM_AGENT_LOG_FORMAT`, `CLAIM_AGENT_LOG_LEVEL`, `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `CLAIM_AGENT_TRACE_LLM`, `CLAIM_AGENT_TRACE_TOOLS`. See [Observability](observability.md) for full details.

### PII and Retention

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAIM_AGENT_MASK_PII` | `true` | Mask policy_number and vin in logs. Set `false` for dev. |
| `RETENTION_PERIOD_YEARS` | 5 (from compliance) | Override retention period. Run `claim-agent retention-enforce` to archive. |
| `STATE_RETENTION_PATH` | `data/state_retention_periods.json` | Path to state-specific retention periods (per-state years). |

See [PII and Retention](pii-and-retention.md) for full documentation.

### Reserve management

Carrier case reserves (estimated ultimate cost) are stored on `claims.reserve_amount` with an append-only `reserve_history` table. Adjusters set reserves via `PATCH /api/claims/{claim_id}/reserve` (subject to limits); supervisors/admins use higher ceilings. See [Database](database.md#reserve_history).

| Variable | Default | Description |
|----------|---------|-------------|
| `RESERVE_ADJUSTER_LIMIT` | `10000` | Maximum reserve amount an adjuster may set |
| `RESERVE_SUPERVISOR_LIMIT` | `50000` | Maximum reserve for `supervisor` / `admin` roles |
| `RESERVE_INITIAL_RESERVE_FROM_ESTIMATED_DAMAGE` | `true` | When true, FNOL creates an initial reserve from `estimated_damage` when present |

Escalation, fraud detection, valuation, and partial-loss thresholds are also configurable via environment variables. See [Centralized Settings](#centralized-settings) and `.env.example` for the full list.

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

## Centralized Settings

Configuration is loaded via a Pydantic Settings model at startup. All environment variables are validated and typed. Use `get_settings()` for direct access:

```python
from claim_agent.config import get_settings

settings = get_settings()
# Typed access: settings.router.confidence_threshold, settings.paths.claims_db_path, etc.
```

The module `src/claim_agent/config/settings.py` provides backward-compatible functions that delegate to `get_settings()`:

| Function / Constant | Purpose |
|---------------------|---------|
| `get_router_config()` | Router confidence threshold, validation enabled |
| `get_coverage_config()` | FNOL coverage verification (enabled, deny when deductible exceeds damage) |
| `get_escalation_config()` | Escalation thresholds (confidence, high value, similarity range, etc.) |
| `get_fraud_config()` | Fraud detection scores and thresholds |
| `get_crew_verbose()` | Whether CrewAI runs in verbose mode |
| `get_mask_pii()` | Whether to mask PII in logs (from `CLAIM_AGENT_MASK_PII`) |
| `get_retention_period_years()` | Retention period from compliance or `RETENTION_PERIOD_YEARS` |
| `get_retention_by_state()` | State-specific retention periods (years) from `STATE_RETENTION_PATH` |
| `get_api_keys_config()` | API keys mapping (key -> role) from `API_KEYS` or `CLAIMS_API_KEY` |
| `get_jwt_secret()` | JWT secret for Bearer token verification, or None |
| `MAX_TOKENS_PER_CLAIM`, `MAX_LLM_CALLS_PER_CLAIM` | Token and call budgets per claim |
| `DEFAULT_BASE_VALUE`, `DEPRECIATION_PER_YEAR`, etc. | Valuation and partial-loss defaults |
| `get_adapter_backend(name)` | Configured adapter backend for a given adapter name |

Router variables: `ROUTER_CONFIDENCE_THRESHOLD` (default 0.7), `ROUTER_VALIDATION_ENABLED` (default false). When `ROUTER_VALIDATION_ENABLED=true`, the optional second-pass validation LLM call uses `OPENAI_MODEL_NAME` (the same variable that controls all other LLM calls; default `gpt-4o-mini`).

Coverage verification: `COVERAGE_ENABLED` (default true) enables FNOL coverage verification before routing. When enabled, claims are checked for active policy, physical damage coverage, and optionally `COVERAGE_DENY_WHEN_DEDUCTIBLE_EXCEEDS_DAMAGE` (default false) to deny when deductible exceeds estimated damage.

Duplicate detection: `DUPLICATE_SIMILARITY_THRESHOLD` (default 40), `DUPLICATE_SIMILARITY_THRESHOLD_HIGH_VALUE` (default 60), `DUPLICATE_DAYS_WINDOW` (default 3). These control when claims with the same VIN are considered duplicates for routing.

High-value thresholds: `HIGH_VALUE_DAMAGE_THRESHOLD` (default 25000), `HIGH_VALUE_VEHICLE_THRESHOLD` (default 50000). Claims exceeding these use stricter duplicate similarity thresholds.

Pre-routing fraud: `PRE_ROUTING_FRAUD_DAMAGE_RATIO` (default 0.9). When damage-to-value ratio exceeds this and damage is not catastrophic, pre-routing fraud indicators are evaluated.

Escalation variables: `ESCALATION_CONFIDENCE_THRESHOLD`, `ESCALATION_HIGH_VALUE_THRESHOLD`, `ESCALATION_SIMILARITY_AMBIGUOUS_RANGE`, `ESCALATION_FRAUD_DAMAGE_VS_VALUE_RATIO`, `ESCALATION_VIN_CLAIMS_DAYS`, `ESCALATION_CONFIDENCE_DECREMENT_PER_PATTERN`, `ESCALATION_DESCRIPTION_OVERLAP_THRESHOLD`. Mid-workflow escalation SLA hours: `ESCALATION_SLA_HOURS_CRITICAL` (24), `ESCALATION_SLA_HOURS_HIGH` (24), `ESCALATION_SLA_HOURS_MEDIUM` (48), `ESCALATION_SLA_HOURS_LOW` (72). Low-confidence router escalations (always medium priority) use `ESCALATION_SLA_HOURS_MEDIUM`. `ROUTER_ESCALATION_SLA_HOURS` is deprecated in favor of the unified `ESCALATION_SLA_HOURS_*` constants.

Fraud variables: `FRAUD_MULTIPLE_CLAIMS_DAYS`, `FRAUD_MULTIPLE_CLAIMS_THRESHOLD`, `FRAUD_*_SCORE`, `FRAUD_*_THRESHOLD`, `FRAUD_CRITICAL_INDICATOR_COUNT`.

Valuation/partial loss: `VALUATION_*`, `PARTIAL_LOSS_*`. See `.env.example` for all variable names and defaults.

## LLM Configuration Code

The module uses `load_dotenv()` and sets up observability (e.g. LangSmith) on first LLM use:

```python
# src/claim_agent/config/llm.py (simplified)

def get_llm():
    """Return the configured LLM for agents. Requires OPENAI_API_KEY."""
    setup_observability()  # LangSmith etc., called once on first LLM use

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
├── .env.example            # Template for .env (all env vars documented)
├── data/
│   ├── claims.db           # SQLite database (created automatically)
│   ├── mock_db.json        # Policy and vehicle data
│   ├── california_auto_compliance.json
│   └── *_auto_policy_language.json
└── src/claim_agent/
    ├── config/
    │   ├── llm.py          # LLM configuration
    │   ├── settings.py     # Centralized settings (escalation, fraud, valuation, token budgets)
    │   ├── agents.yaml     # Agent reference
    │   └── tasks.yaml      # Task reference
    └── skills/
        ├── __init__.py     # Skill loading utilities
        └── *.md            # Agent skill definitions
```

## Logging and Verbose Mode

CrewAI verbose mode is controlled by `CREWAI_VERBOSE` (default: `true`). Set to `false` to reduce crew output. For general Python logging:

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

See `.env.example` in the project root for the full list of variables. Minimal example:

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

# Optional: Escalation, fraud, valuation, token budgets, CREWAI_VERBOSE
# See .env.example for all options.
```
