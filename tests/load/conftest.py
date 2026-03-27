"""Shared fixtures for load tests."""

import tempfile
import threading

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def load_client(temp_db, monkeypatch):
    """Create a TestClient for load tests with mocked workflow."""
    with tempfile.TemporaryDirectory() as storage_path:
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", storage_path)
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.delenv("API_KEYS", raising=False)
        import claim_agent.storage.factory as factory_mod
        monkeypatch.setattr(factory_mod, "_storage_instance", None)

        from claim_agent.api.server import app
        yield TestClient(app)


@pytest.fixture
def mock_workflow_for_load(monkeypatch):
    """Mock run_claim_workflow to return quickly for load testing."""
    import claim_agent.api.routes.claims_crud as claims_crud_mod

    call_count = [0]
    lock = threading.Lock()

    def mock_wf(claim_data, llm=None, existing_claim_id=None, *, actor_id=None, ctx=None, **kwargs):
        with lock:
            call_count[0] += 1
            count = call_count[0]
        cid = existing_claim_id or f"CLM-LOAD-{count:05d}"
        return {
            "claim_id": cid,
            "claim_type": "new",
            "status": "open",
            "summary": "Load test mock.",
        }

    monkeypatch.setattr(claims_crud_mod, "run_claim_workflow", mock_wf)
    yield
