"""Shared fixtures for load tests."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def load_client(temp_db, monkeypatch):
    """Create a TestClient for load tests with mocked workflow."""
    with tempfile.TemporaryDirectory() as storage_path:
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", storage_path)
        import claim_agent.storage.factory as factory_mod
        monkeypatch.setattr(factory_mod, "_storage_instance", None)
        os.environ.pop("CLAIMS_API_KEY", None)
        os.environ.pop("API_KEYS", None)

        from claim_agent.api.server import app
        yield TestClient(app)


@pytest.fixture
def mock_workflow_for_load(monkeypatch):
    """Mock run_claim_workflow to return quickly for load testing."""
    import claim_agent.api.routes.claims as claims_mod

    call_count = [0]

    def mock_wf(claim_data, llm=None, existing_claim_id=None, *, actor_id=None):
        call_count[0] += 1
        cid = existing_claim_id or f"CLM-LOAD-{call_count[0]:05d}"
        return {
            "claim_id": cid,
            "claim_type": "new",
            "status": "open",
            "summary": "Load test mock.",
        }

    monkeypatch.setattr(claims_mod, "run_claim_workflow", mock_wf)
    yield
