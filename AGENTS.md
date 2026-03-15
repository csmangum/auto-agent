# AGENTS.md – AI Assistant Guide

Guidance for AI coding assistants (Cursor, Copilot, etc.) working on the Agentic Claim Representative codebase.

## Project Overview

**Agentic Claim Representative** is a proof-of-concept AI system for processing auto insurance claims. It uses [CrewAI](https://crewai.com/) and Python with a multi-agent architecture: a Router classifies claims and delegates to specialized crews (New, Duplicate, Total Loss, Fraud, Partial Loss, Bodily Injury, Reopened).

Key capabilities: workflow routing, human-in-the-loop escalation, persistent SQLite state, RAG over policy/compliance, webhooks, pluggable adapters, file attachments, and an optional MCP server.

## Tech Stack

- **Python 3.10+**
- **CrewAI** – multi-agent orchestration
- **FastAPI** – REST API
- **SQLite** – claims and audit storage
- **Pydantic** – models and settings
- **Alembic** – DB migrations
- **React + Vite** – observability dashboard (frontend)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env with OPENAI_API_KEY (OpenRouter or OpenAI)
```

Unit tests use a venv; no API key needed for unit/integration/E2E tests (LLM is mocked).

## Project Layout

```
src/claim_agent/
├── main.py           # CLI entry point (claim-agent)
├── api/              # FastAPI routes, auth, deps
├── config/           # LLM (llm.py), settings (settings.py)
├── agents/           # Agent definitions
├── crews/            # Crew definitions (router, workflows)
├── skills/           # Agent prompts (markdown)
├── tools/            # CrewAI tools
├── adapters/         # Policy, valuation, repair, parts, SIU
├── mock_crew/        # Mock claimant, vision, image gen (testing)
├── rag/              # RAG pipeline (policy/compliance)
├── storage/          # Local and S3 attachment storage
├── notifications/    # Webhooks, claimant notifications
├── utils/            # Sanitization, retry
├── db/               # SQLite database
├── models/           # Pydantic models
├── observability/    # Logging, tracing, metrics
└── mcp_server/       # Optional MCP server
```

## Testing

```bash
# Unit tests (no API key, no LLM)
export MOCK_DB_PATH=data/mock_db.json
pytest tests/ -v --ignore=tests/integration --ignore=tests/e2e --ignore=tests/load \
  -m "not slow and not integration and not llm and not e2e and not load"

# Integration tests (mocked LLM)
pytest tests/integration/ -v -m "integration and not slow and not llm"

# E2E tests (API-based, mocked LLM)
pytest tests/e2e/ -v -m e2e

# Load tests
LOAD_TEST_CONCURRENCY=20 pytest tests/load/ -v -m load -s
```

Use `.venv` for running tests. Default pytest markers exclude `llm`; use `-m llm` only when API key is available.

## Conventions

- **Backwards compatibility**: Not required; refactor freely.
- **Linting**: Ruff (E, F), line length 100.
- **Type checking**: mypy (warn_return_any, warn_unused_configs).
- **DB changes**: Use Alembic (`alembic revision -m "..."`, `alembic upgrade head`).
- **Configuration**: Centralized in `config/settings.py`; env vars in `.env.example`.

## Common Tasks

| Task | Command / Location |
|------|--------------------|
| Process a claim | `claim-agent process tests/sample_claims/partial_loss_parking.json` |
| Start API server | `claim-agent serve [--reload]` |
| Start dashboard | `claim-agent serve` + `cd frontend && npm run dev` |
| Run migrations | `alembic upgrade head` |
| Create migration | `alembic revision -m "description"` |
| Seed mock data | `python scripts/seed_claims_from_mock_db.py` |
| Run evaluation | `python scripts/evaluate_claim_processing.py --quick` |

## Key Patterns

- **Router–Delegator**: Router classifies claims; workflow crews handle each type.
- **Escalation**: Fraud indicators, high value, or low confidence → `needs_review`.
- **Adapters**: Pluggable backends (policy, valuation, repair, SIU) via registry.
- **Mock Crew**: `MOCK_CREW_ENABLED=true`, `VISION_ADAPTER=mock` for testing without external APIs.

## Documentation

- `docs/` – Architecture, crews, skills, claim types, tools, adapters, DB, config, observability, RAG, MCP, mock crew, alerting.
- `README.md` – Quick start, CLI reference, sample claims, testing.

## Sample Claims

Located in `tests/sample_claims/`: `new_claim.json`, `partial_loss_parking.json`, `duplicate_claim.json`, `total_loss_claim.json`, `fraud_claim.json`, `bodily_injury_claim.json`, etc.
