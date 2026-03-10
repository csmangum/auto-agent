"""Shared fixtures for E2E tests.

E2E tests submit claims via the REST API and assert outcomes.
Database, sample claims, and mock LLM fixtures come from tests.conftest_shared.
"""

import shutil
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def temp_db():
    """Override root temp_db - E2E tests use integration_db explicitly."""
    yield None


@pytest.fixture
def e2e_client(integration_db: str, monkeypatch):
    """Create a TestClient for the FastAPI app, bound to integration_db.

    CLAIMS_DB_PATH is set by integration_db fixture before the client is created.
    """
    from claim_agent.api.server import app

    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    monkeypatch.delenv("API_KEYS", raising=False)

    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", tmpdir)

    try:
        yield TestClient(app)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
