"""Shared fixtures for integration tests.

This module provides fixtures for integration tests.
Database, sample claims, and mock LLM fixtures come from tests.conftest_shared.
"""

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Generator

import pytest

# Ensure project paths are set
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Set MOCK_DB_PATH for all tests
os.environ.setdefault("MOCK_DB_PATH", str(DATA_DIR / "mock_db.json"))


@pytest.fixture(autouse=True)
def temp_db():
    """Override root autouse temp_db - integration tests use integration_db explicitly."""
    yield None


# Base date for seeded_db claims (shared so tests can search by it)
_SEEDED_BASE_DATE = date.today() - timedelta(days=30)


@pytest.fixture
def seeded_db_base_date() -> str:
    """Base incident date used for first claim in seeded_db (for tests that search by date)."""
    return _SEEDED_BASE_DATE.isoformat()


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
    base_date = _SEEDED_BASE_DATE

    # Seed with sample claims (relative dates for stability)
    sample_claims = [
        {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": base_date.isoformat(),
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
            "incident_date": (base_date + timedelta(days=5)).isoformat(),
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
            "incident_date": (base_date + timedelta(days=10)).isoformat(),
            "incident_description": "Vehicle totaled in flood.",
            "damage_description": "Total loss - flood damage.",
            "estimated_damage": 15000,
        },
    ]
    
    for claim_data in sample_claims:
        repo.create_claim(ClaimInput(**claim_data))

    yield integration_db


@pytest.fixture
def api_client(integration_db: str):
    """TestClient bound to integration_db for API integration tests."""
    from fastapi.testclient import TestClient

    from claim_agent.api.server import app

    return TestClient(app)


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


