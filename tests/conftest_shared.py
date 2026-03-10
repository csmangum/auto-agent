"""Shared fixtures for integration and E2E tests.

Provides integration_db, sample claim loaders, and mock LLM fixtures
used by both tests/integration and tests/e2e.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Generator
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
def sample_new_claim() -> dict:
    """Load sample new claim data."""
    with open(SAMPLE_CLAIMS_DIR / "new_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_fraud_claim() -> dict:
    """Load sample fraud claim data."""
    with open(SAMPLE_CLAIMS_DIR / "fraud_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_total_loss_claim() -> dict:
    """Load sample total loss claim data."""
    with open(SAMPLE_CLAIMS_DIR / "total_loss_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_duplicate_claim() -> dict:
    """Load sample duplicate claim data."""
    with open(SAMPLE_CLAIMS_DIR / "duplicate_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_partial_loss_claim() -> dict:
    """Load sample partial loss claim data."""
    with open(SAMPLE_CLAIMS_DIR / "partial_loss_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_bodily_injury_claim() -> dict:
    """Load sample bodily injury claim data."""
    with open(SAMPLE_CLAIMS_DIR / "bodily_injury_claim.json") as f:
        return json.load(f)


# ============================================================================
# Mock LLM Fixtures
# ============================================================================


@pytest.fixture
def mock_router_response():
    """Factory fixture for creating mock router responses."""
    def _create_response(claim_type: str, reasoning: str = "Test reasoning."):
        mock_result = MagicMock()
        mock_result.raw = f"{claim_type}\n{reasoning}"
        mock_result.output = f"{claim_type}\n{reasoning}"
        return mock_result
    return _create_response


@pytest.fixture
def mock_crew_response():
    """Factory fixture for creating mock crew responses."""
    def _create_response(output: str, tasks_output=None):
        mock_result = MagicMock()
        mock_result.raw = output
        mock_result.output = output
        if tasks_output is not None:
            mock_result.tasks_output = tasks_output
        return mock_result
    return _create_response
