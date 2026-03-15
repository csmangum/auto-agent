"""Shared fixtures for integration and E2E tests.

Provides integration_db, sample claim loaders, and mock LLM fixtures
used by both tests/integration and tests/e2e.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Generator
from unittest.mock import MagicMock

import pytest

SAMPLE_CLAIMS_DIR = Path(__file__).resolve().parent / "sample_claims"


@pytest.fixture
def integration_db() -> Generator[str, None, None]:
    """Create a temporary SQLite database for integration/E2E tests.

    Provides a clean database per test with CLAIMS_DB_PATH set.
    """
    from claim_agent.db.database import init_db

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    prev = os.environ.get("CLAIMS_DB_PATH")
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        yield path
    finally:
        if prev is None:
            os.environ.pop("CLAIMS_DB_PATH", None)
        else:
            os.environ["CLAIMS_DB_PATH"] = prev
        try:
            os.unlink(path)
        except OSError:
            pass


# ============================================================================
# Sample Claim Data Fixtures
# ============================================================================


@pytest.fixture
def sample_new_claim() -> dict[str, Any]:
    """Load sample new claim data."""
    with open(SAMPLE_CLAIMS_DIR / "new_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_fraud_claim() -> dict[str, Any]:
    """Load sample fraud claim data."""
    with open(SAMPLE_CLAIMS_DIR / "fraud_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_total_loss_claim() -> dict[str, Any]:
    """Load sample total loss claim data."""
    with open(SAMPLE_CLAIMS_DIR / "total_loss_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_duplicate_claim() -> dict[str, Any]:
    """Load sample duplicate claim data."""
    with open(SAMPLE_CLAIMS_DIR / "duplicate_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_partial_loss_claim() -> dict[str, Any]:
    """Load sample partial loss claim data."""
    with open(SAMPLE_CLAIMS_DIR / "partial_loss_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_bodily_injury_claim() -> dict[str, Any]:
    """Load sample bodily injury claim data."""
    with open(SAMPLE_CLAIMS_DIR / "bodily_injury_claim.json") as f:
        return json.load(f)


# ============================================================================
# Mock LLM Fixtures
# ============================================================================


def _mock_llm_for_crew() -> MagicMock:
    """Return a MagicMock configured for CrewAI Agent validation.

    CrewAI's Agent requires llm.model to be a non-empty string.
    """
    m = MagicMock()
    m.model = "mock-model"
    return m


@pytest.fixture
def mock_llm_instance() -> MagicMock:
    """Fixture providing a mock LLM that satisfies CrewAI Agent validation."""
    return _mock_llm_for_crew()


@pytest.fixture
def mock_router_response() -> Callable[[str, str], MagicMock]:
    """Factory fixture for creating mock router responses."""
    def _create_response(claim_type: str, reasoning: str = "Test reasoning.") -> MagicMock:
        mock_result = MagicMock()
        mock_result.raw = f"{claim_type}\n{reasoning}"
        mock_result.output = f"{claim_type}\n{reasoning}"
        return mock_result
    return _create_response


@pytest.fixture
def mock_crew_response() -> Callable[..., MagicMock]:
    """Factory fixture for creating mock crew responses."""
    def _create_response(output: str, tasks_output: Any = None) -> MagicMock:
        mock_result = MagicMock()
        mock_result.raw = output
        mock_result.output = output
        if tasks_output is not None:
            mock_result.tasks_output = tasks_output
        return mock_result
    return _create_response
