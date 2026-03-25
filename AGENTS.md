# AGENTS.md – AI Assistant Guide

Guidance for AI coding assistants (Cursor, Copilot, etc.) working on the Agentic Claim Representative codebase.

## Project Overview

**Agentic Claim Representative** is a proof-of-concept AI system for processing auto insurance claims. It uses [CrewAI](https://crewai.com/) and Python with a multi-agent architecture: a Router classifies claims and delegates to specialized crews. **Primary claim-type workflows** are New, Duplicate, Total Loss, Fraud, Partial Loss, Bodily Injury, and Reopened; **cross-cutting crews and orchestrators** also cover settlement, escalation, follow-up, supplemental, dispute, denial/coverage, salvage, claim review, after-action, and related stages.

Key capabilities: workflow routing, human-in-the-loop escalation, persistent state (SQLite or PostgreSQL), RAG over policy/compliance, webhooks, pluggable adapters, file attachments, and an optional MCP server.

## Tech Stack

- **Python 3.10+**
- **CrewAI** – multi-agent orchestration
- **FastAPI** – REST API
- **SQLAlchemy + Alembic** – database access and migrations (**SQLite** default; **PostgreSQL** when `DATABASE_URL` is set)
- **Pydantic** – models and settings
- **React + Vite** – observability dashboard (`frontend/`)

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
├── context.py        # ClaimContext for CLI/API
├── events.py         # Event handling
├── exceptions.py     # ClaimAgentError and domain exceptions
├── rbac_roles.py     # RBAC role name constants
├── api/              # FastAPI routes, auth, deps
├── config/           # LLM (llm.py), protocol (llm_protocol.py), settings (settings.py, settings_model.py)
├── agents/           # Agent definitions
├── chat/             # Chat agent for claimant portal
├── compliance/       # UCSPA and regulatory compliance
├── privacy/          # Cross-border transfer and DPA-related helpers
├── crews/            # Crew definitions (router, workflows)
├── data/             # Data loaders
├── diary/            # Diary/calendar system (auto-create, escalation)
├── workflow/         # Orchestration, routing, escalation, handback, dispute, SIU, etc.
├── services/         # Business logic services (adjuster, DSAR)
├── skills/           # Agent prompts (markdown)
├── tools/            # CrewAI tools
├── adapters/         # Policy, valuation, repair, parts, SIU
├── mock_crew/        # Mock claimant, vision, image gen (testing)
├── rag/              # RAG pipeline (policy/compliance)
├── storage/          # Local and S3 attachment storage
├── notifications/    # Webhooks, claimant notifications
├── utils/            # Sanitization, retry
├── db/               # Database layer (SQLite / PostgreSQL)
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

Use `.venv` for running tests. `pyproject.toml` sets default pytest `addopts` to `-m "not llm"`, so a plain `pytest` run also skips LLM tests unless you override markers. Use `-m llm` only when an API key is available.

## Conventions

- **Backwards compatibility**: Not required; refactor freely.
- **Linting**: Ruff (E, F), line length 100.
- **Type checking**: mypy (warn_return_any, warn_unused_configs).
- **DB changes**: Use Alembic (`alembic revision -m "..."`, `alembic upgrade head`).
- **Configuration**: Centralized in `config/settings.py` and `config/settings_model.py`; env vars in `.env.example`.

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
| Full CLI reference | `README.md` (CLI Commands table) |

## Key Patterns

- **Router–Delegator**: Router classifies claims; workflow crews handle each type.
- **Escalation**: Fraud indicators, high value, or low confidence → `needs_review`.
- **Adapters**: Pluggable backends (policy, valuation, repair, SIU) via registry.
- **Mock Crew**: `MOCK_CREW_ENABLED=true`, `VISION_ADAPTER=mock` for testing without external APIs.

## Documentation

- `docs/` – Architecture, crews, skills, claim types, tools, adapters, DB, config, observability, RAG, MCP, mock crew, alerting.
- `README.md` – Quick start, CLI reference, sample claims, testing.

## Sample Claims

Files in `tests/sample_claims/` include:

| File | Notes |
|------|--------|
| `new_claim.json` | New claim |
| `duplicate_claim.json` | Duplicate |
| `total_loss_claim.json` | Total loss |
| `fraud_claim.json` | Fraud |
| `partial_loss_claim.json`, `partial_loss_parking.json`, `partial_loss_fender.json`, `partial_loss_front_collision.json` | Partial loss variants |
| `bodily_injury_claim.json` | Bodily injury |
| `reopened_claim.json` | Reopened |
| `coverage_denied_theft.json` | Coverage denied (theft) |
| `territory_denied_mexico.json` | Territory / jurisdiction |
| `multi_vehicle_incident.json` | Multi-vehicle / incident grouping |

See `README.md` for a shorter curated table.

## Cursor Cloud specific instructions

### Services

| Service | How to start | Port |
|---------|-------------|------|
| FastAPI backend | `MOCK_DB_PATH=data/mock_db.json MOCK_CREW_ENABLED=true .venv/bin/claim-agent serve --reload` | 8000 |
| React dashboard | `cd frontend && npm run dev` | 5173 (proxies `/api` to backend) |
| Claimant portal (self-service) | Same Vite dev server; open `http://localhost:5173/portal/login` (`CLAIMANT_PORTAL_ENABLED=true` on backend) | 5173 |

The backend uses SQLite by default (`data/claims.db`, auto-created). No external databases required for dev/test.

### Running tests

- Always use `.venv/bin/pytest` (not system pytest).
- Set `MOCK_DB_PATH=data/mock_db.json` before running tests.
- The full unit test suite (103 files) takes **15+ minutes** due to sentence-transformers model loading (~88 MB download on first run) and heavy computation. For faster feedback, run targeted tests: `.venv/bin/pytest tests/test_<specific>.py -v`.
- Frontend tests: `cd frontend && npm run test` (vitest, ~13 s).
- See the Testing section above for the full pytest commands with markers.

### Lint / type-check

- Python lint: `.venv/bin/ruff check src/ tests/`
- Python types: `.venv/bin/mypy src/claim_agent/ --ignore-missing-imports`
- Frontend lint: `cd frontend && npm run lint`

### Non-obvious caveats

- **`claim-agent process` / workflow agents** need a valid `OPENAI_API_KEY` (or `OPENROUTER_API_KEY` when using OpenRouter); placeholder values in `.env` are rejected in `get_llm()`. **Unit/integration/E2E tests** mock the LLM and do not need a key. **`MOCK_CREW_ENABLED=true`** mocks external integrations (claimant, vision, webhooks, etc.)—not the CrewAI workflow LLM.
- The `.env` file must exist (copy from `.env.example`) even for testing; Pydantic settings reads it at import time.
- CrewAI prompts for tracing preferences interactively on first run; the CLI auto-times-out after 20 s. This is harmless but may cause a `Fatal Python error` message at process exit — it is cosmetic and does not affect results.
- `mypy` takes ~60 s on the full `src/claim_agent/` tree.
