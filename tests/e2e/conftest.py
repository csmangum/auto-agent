"""Shared fixtures for E2E tests.

E2E tests submit claims via the REST API and assert outcomes.
Reuses integration fixtures for database and sample claims.
"""

import os
import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient

# Load integration conftest to reuse integration_db, sample_*_claim, mock_* fixtures
pytest_plugins = ["tests.integration.conftest"]


@pytest.fixture(autouse=True)
def temp_db():
    """Override root temp_db - E2E tests use integration_db explicitly."""
    yield None


@pytest.fixture
def e2e_client(integration_db: str):
    """Create a TestClient for the FastAPI app, bound to integration_db.

    CLAIMS_DB_PATH is set by integration_db fixture before the client is created.
    """
    from claim_agent.api.server import app

    # Ensure no auth required so tests run without API key
    os.environ.pop("CLAIMS_API_KEY", None)
    os.environ.pop("API_KEYS", None)

    # Set attachment storage for claim creation
    tmpdir = tempfile.mkdtemp()
    os.environ["ATTACHMENT_STORAGE_PATH"] = tmpdir

    try:
        yield TestClient(app)
    finally:
        os.environ.pop("ATTACHMENT_STORAGE_PATH", None)
        shutil.rmtree(tmpdir, ignore_errors=True)
