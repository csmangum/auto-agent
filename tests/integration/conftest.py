"""Shared fixtures for integration tests.

This module provides fixtures that are commonly needed for integration tests,
including database setup, mock LLM configurations, and test data loading.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock

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


