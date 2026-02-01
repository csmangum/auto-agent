# Integration Tests

Integration tests verify that different components of the claim agent system work correctly together, testing realistic workflows and data flows between modules.

## Running Tests

### Using the runner script (recommended)

From the project root:

```bash
./scripts/run_integration_tests.sh [options]
```

**Test subsets:**

| Option | Description |
|--------|-------------|
| `--all` | Run all integration tests |
| `--fast` | Run fast integration tests only (skip slow and LLM tests) |
| `--llm` | Run tests that require LLM API access |
| `--rag` | Run RAG-specific tests |
| `--db` | Run database tests |
| `--tools` | Run tools tests |
| `--mcp` | Run MCP server tests |
| `--workflow` | Run workflow tests |
| `--coverage` | Generate coverage report (term + html) |
| `-v`, `--verbose` | Verbose output |
| `-h`, `--help` | Show help |

Default (no options): runs all tests marked `integration`.

### Using pytest directly

```bash
# All integration tests
pytest tests/integration/ -m integration

# Fast subset (no slow, no LLM)
pytest tests/integration/ -m "integration and not slow and not llm"

# With coverage
pytest tests/integration/ -m integration --cov=claim_agent --cov-report=term-missing
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `MOCK_DB_PATH` | No (default: `data/mock_db.json`) | Path to mock policy/DB JSON for tools |
| `CLAIMS_DB_PATH` | No (set by fixtures) | SQLite claims DB path; integration tests use temp DBs |
| `OPENAI_API_KEY` | For `llm` / `e2e` tests | Set to run live LLM workflow tests; omit to skip them |

## Test Markers

Defined in `pyproject.toml`:

| Marker | Meaning |
|--------|---------|
| `integration` | Integration test (component interactions) |
| `slow` | Slower test (e.g. model loading, heavy computation) |
| `llm` | Requires LLM API access (`OPENAI_API_KEY`) |
| `e2e` | End-to-end workflow test |

Examples:

```bash
pytest tests/integration/ -m integration
pytest tests/integration/ -m "integration and not slow"
pytest tests/integration/ -m llm
```

## Test Categories

| File | Focus |
|------|--------|
| `test_workflow.py` | End-to-end claim workflow, routing, escalation, reprocessing |
| `test_database.py` | DB init, repository CRUD, audit log, search, workflow_runs |
| `test_tools.py` | Policy, claims, valuation, fraud, partial loss, escalation, document, compliance tools |
| `test_rag.py` | RAG retriever, context provider, tools, skills (requires `sentence_transformers`) |
| `test_mcp.py` | MCP server tools and pipelines |

## CI Integration

- Use **bash** to run `scripts/run_integration_tests.sh` (script checks for bash).
- For CI, use the fast subset to avoid slow and LLM tests unless you provide `OPENAI_API_KEY`:
  ```bash
  ./scripts/run_integration_tests.sh --fast
  ```
- RAG tests are skipped if `sentence_transformers` is not installed (`pytest.importorskip("sentence_transformers")`).
- Activate the project virtualenv before running (script will try `venv` or `.venv` if `VIRTUAL_ENV` is unset).
