"""Shared fixtures for integration tests.

This module provides fixtures that are commonly needed for integration tests,
including database setup, mock LLM configurations, and test data loading.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

# Ensure project paths are set
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
SAMPLE_CLAIMS_DIR = Path(__file__).parent.parent / "sample_claims"

# Set MOCK_DB_PATH for all tests
os.environ.setdefault("MOCK_DB_PATH", str(DATA_DIR / "mock_db.json"))


# ============================================================================
# Database Fixtures
# ============================================================================


@pytest.fixture
def integration_db() -> Generator[str, None, None]:
    """Create a temporary SQLite database for integration tests.
    
    This fixture provides a clean database for each test and automatically
    cleans up after the test completes.
    
    Yields:
        str: Path to the temporary database file.
    """
    from claim_agent.db.database import init_db
    
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    
    try:
        init_db(path)
        prev = os.environ.get("CLAIMS_DB_PATH")
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


@pytest.fixture
def seeded_db(integration_db: str) -> Generator[str, None, None]:
    """Create a database pre-seeded with sample claims.
    
    This fixture builds on integration_db and adds sample claims for testing
    duplicate detection, search, and other scenarios.
    
    Yields:
        str: Path to the seeded database file.
    """
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput
    
    repo = ClaimRepository(db_path=integration_db)
    
    # Seed with sample claims
    sample_claims = [
        {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended at stoplight.",
            "damage_description": "Rear bumper and trunk damaged.",
            "estimated_damage": 3500,
        },
        {
            "policy_number": "POL-002",
            "vin": "5YJSA1E26HF123456",
            "vehicle_year": 2022,
            "vehicle_make": "Tesla",
            "vehicle_model": "Model 3",
            "incident_date": "2025-01-20",
            "incident_description": "Minor fender bender in parking lot.",
            "damage_description": "Front bumper scratch.",
            "estimated_damage": 1200,
        },
        {
            "policy_number": "POL-003",
            "vin": "JM1BL1S58A1234567",
            "vehicle_year": 2020,
            "vehicle_make": "Mazda",
            "vehicle_model": "3",
            "incident_date": "2025-01-25",
            "incident_description": "Vehicle totaled in flood.",
            "damage_description": "Total loss - flood damage.",
            "estimated_damage": 15000,
        },
    ]
    
    for claim_data in sample_claims:
        repo.create_claim(ClaimInput(**claim_data))
    
    yield integration_db


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
def sample_partial_loss_claim() -> dict:
    """Load sample partial loss claim data."""
    with open(SAMPLE_CLAIMS_DIR / "partial_loss_claim.json") as f:
        return json.load(f)


@pytest.fixture
def sample_duplicate_claim() -> dict:
    """Load sample duplicate claim data."""
    with open(SAMPLE_CLAIMS_DIR / "duplicate_claim.json") as f:
        return json.load(f)


@pytest.fixture
def all_sample_claims(
    sample_new_claim,
    sample_fraud_claim,
    sample_total_loss_claim,
    sample_partial_loss_claim,
    sample_duplicate_claim,
) -> dict:
    """All sample claims by type."""
    return {
        "new": sample_new_claim,
        "fraud": sample_fraud_claim,
        "total_loss": sample_total_loss_claim,
        "partial_loss": sample_partial_loss_claim,
        "duplicate": sample_duplicate_claim,
    }


# ============================================================================
# Mock LLM Fixtures
# ============================================================================


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns configurable responses.
    
    This fixture is useful for testing workflow logic without making actual
    LLM API calls. The mock can be configured with specific responses.
    """
    mock = MagicMock()
    mock.invoke.return_value = MagicMock(content="new\nStandard claim submission.")
    return mock


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
    def _create_response(output: str):
        mock_result = MagicMock()
        mock_result.raw = output
        mock_result.output = output
        return mock_result
    return _create_response


# ============================================================================
# RAG Fixtures
# ============================================================================


@pytest.fixture
def rag_cache_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for RAG cache.
    
    Yields:
        Path: Path to the temporary cache directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def policy_retriever(rag_cache_dir: Path):
    """Create a PolicyRetriever instance with temporary cache.
    
    This fixture is marked slow because it may need to load embedding models.
    """
    pytest.importorskip("sentence_transformers")
    
    from claim_agent.rag.retriever import PolicyRetriever
    
    return PolicyRetriever(
        data_dir=DATA_DIR,
        cache_dir=rag_cache_dir,
        auto_load=True,
    )


# ============================================================================
# Environment Control Fixtures
# ============================================================================


@pytest.fixture
def skip_if_no_api_key():
    """Skip test if OPENAI_API_KEY is not set."""
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set; skipping LLM-dependent test")


@pytest.fixture
def clean_environment():
    """Ensure a clean environment for testing.
    
    Saves and restores environment variables that might affect tests.
    """
    saved_env = {}
    env_vars_to_save = [
        "CLAIMS_DB_PATH",
        "MOCK_DB_PATH",
        "CLAIM_AGENT_CACHE_DIR",
        "OPENAI_API_KEY",
        "OPENAI_API_BASE",
        "OPENAI_MODEL_NAME",
    ]
    
    for var in env_vars_to_save:
        saved_env[var] = os.environ.get(var)
    
    yield
    
    for var, value in saved_env.items():
        if value is None:
            os.environ.pop(var, None)
        else:
            os.environ[var] = value


# ============================================================================
# Utility Fixtures
# ============================================================================


@pytest.fixture
def assert_claim_in_db(integration_db: str):
    """Factory fixture to assert a claim exists in the database."""
    from claim_agent.db.repository import ClaimRepository
    
    def _assert(claim_id: str, expected_status: str = None):
        repo = ClaimRepository(db_path=integration_db)
        claim = repo.get_claim(claim_id)
        assert claim is not None, f"Claim {claim_id} not found in database"
        if expected_status:
            assert claim["status"] == expected_status, \
                f"Expected status {expected_status}, got {claim['status']}"
        return claim
    
    return _assert


@pytest.fixture
def create_test_claim(integration_db: str):
    """Factory fixture to create test claims in the database."""
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput
    
    def _create(claim_data: dict) -> str:
        repo = ClaimRepository(db_path=integration_db)
        claim_input = ClaimInput(**claim_data)
        return repo.create_claim(claim_input)
    
    return _create
