"""Tests for workflow processing routes defined in claims_workflow.py.

Covers:
- POST /claims/process  (synchronous and async modes)
- POST /claims/process/async
- GET  /claims/{claim_id}/stream
- POST /claims/{claim_id}/reprocess
"""

import json

import pytest
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Shared test payload
# ---------------------------------------------------------------------------

VALID_CLAIM_PAYLOAD = {
    "policy_number": "POL-001",
    "vin": "1HGCM82633A004352",
    "vehicle_year": 2020,
    "vehicle_make": "Honda",
    "vehicle_model": "Accord",
    "incident_date": "2024-01-15",
    "incident_description": "Rear-ended at a stoplight.",
    "damage_description": "Rear bumper cracked, trunk lid damaged.",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all tests in this module."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Reset rate-limit buckets before each test to avoid spurious 429s."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    """Test client wired to the FastAPI application."""
    from claim_agent.api.server import app

    return TestClient(app)


@pytest.fixture
def mock_workflow(monkeypatch):
    """Patch run_claim_workflow in claims_workflow to avoid real LLM calls."""
    mock_result = {
        "claim_id": "CLM-WF-MOCK",
        "claim_type": "new",
        "status": "open",
        "summary": "Workflow mocked.",
    }
    import claim_agent.api.routes.claims_workflow as wf_mod
    import claim_agent.storage.factory as factory_mod

    monkeypatch.setattr(wf_mod, "run_claim_workflow", lambda *a, **kw: mock_result)
    monkeypatch.setattr(factory_mod, "_storage_instance", None)
    return mock_result


# ---------------------------------------------------------------------------
# POST /claims/process – synchronous processing
# ---------------------------------------------------------------------------


class TestProcessClaim:
    """Tests for POST /claims/process (multipart form, sync and async modes)."""

    def test_valid_claim_sync_returns_workflow_result(self, client, mock_workflow, tmp_path, monkeypatch):
        """Valid claim JSON without files returns the workflow result synchronously."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))

        resp = client.post(
            "/api/v1/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-WF-MOCK"

    def test_valid_claim_async_mode_returns_claim_id_only(self, client, mock_workflow, tmp_path, monkeypatch):
        """POST /claims/process?async=true returns {claim_id} immediately without workflow output."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))

        resp = client.post(
            "/api/v1/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
            params={"async": "true"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "claim_id" in data
        assert "status" not in data
        assert "claim_type" not in data

    def test_invalid_json_returns_400(self, client, mock_workflow):
        """Malformed JSON in the 'claim' form field returns 400."""
        resp = client.post(
            "/api/v1/claims/process",
            data={"claim": "not-valid-json{"},
        )
        assert resp.status_code == 400
        assert "Invalid claim JSON" in resp.json()["detail"]

    def test_invalid_claim_data_returns_400(self, client, mock_workflow):
        """Claim data that fails Pydantic validation returns 400."""
        bad_payload = {**VALID_CLAIM_PAYLOAD, "vehicle_year": "not-a-year"}
        resp = client.post(
            "/api/v1/claims/process",
            data={"claim": json.dumps(bad_payload)},
        )
        assert resp.status_code == 400
        assert "Invalid claim data" in resp.json()["detail"]

    def test_with_file_upload_returns_200(self, client, mock_workflow, tmp_path, monkeypatch):
        """Valid claim with an uploaded attachment returns 200."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))

        resp = client.post(
            "/api/v1/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
            files=[("files", ("damage.jpg", b"fake image data", "image/jpeg"))],
        )
        assert resp.status_code == 200

    def test_capacity_exceeded_returns_503(self, client, mock_workflow, tmp_path, monkeypatch):
        """When background task capacity is full, POST /claims/process?async=true returns 503."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        import claim_agent.api.routes._claims_helpers as helpers_mod
        from claim_agent.config import get_settings

        settings = get_settings()
        monkeypatch.setattr(settings, "max_concurrent_background_tasks", 1)
        real_tasks = helpers_mod.background_tasks

        class AtCapacitySet:
            def add(self, x):
                real_tasks.add(x)

            def discard(self, x):
                real_tasks.discard(x)

            def __len__(self):
                return len(real_tasks) + 1

        monkeypatch.setattr(helpers_mod, "background_tasks", AtCapacitySet())

        resp = client.post(
            "/api/v1/claims/process",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
            params={"async": "true"},
        )
        assert resp.status_code == 503
        assert "Too many concurrent" in resp.json()["detail"]
        assert resp.headers.get("Retry-After") == "60"


# ---------------------------------------------------------------------------
# POST /claims/process/async
# ---------------------------------------------------------------------------


class TestProcessClaimAsync:
    """Tests for POST /claims/process/async."""

    def test_returns_claim_id_immediately(self, client, mock_workflow, tmp_path, monkeypatch):
        """Async endpoint returns {claim_id} without waiting for workflow completion."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))

        resp = client.post(
            "/api/v1/claims/process/async",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "claim_id" in data
        assert data["claim_id"].startswith("CLM-")

    def test_capacity_exceeded_does_not_create_claim(self, client, mock_workflow, tmp_path, monkeypatch):
        """Returns 503 when at capacity and does NOT persist a new claim."""
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        import claim_agent.api.routes._claims_helpers as helpers_mod
        from claim_agent.config import get_settings
        from sqlalchemy import text

        from claim_agent.db.database import get_connection

        settings = get_settings()
        monkeypatch.setattr(settings, "max_concurrent_background_tasks", 1)
        real_tasks = helpers_mod.background_tasks

        class AtCapacitySet:
            def add(self, x):
                real_tasks.add(x)

            def discard(self, x):
                real_tasks.discard(x)

            def __len__(self):
                return len(real_tasks) + 1

        monkeypatch.setattr(helpers_mod, "background_tasks", AtCapacitySet())

        with get_connection() as conn:
            count_before = conn.execute(text("SELECT COUNT(*) as c FROM claims")).fetchone()[0]

        resp = client.post(
            "/api/v1/claims/process/async",
            data={"claim": json.dumps(VALID_CLAIM_PAYLOAD)},
        )
        assert resp.status_code == 503
        assert resp.headers.get("Retry-After") == "60"

        with get_connection() as conn:
            count_after = conn.execute(text("SELECT COUNT(*) as c FROM claims")).fetchone()[0]
        assert count_after == count_before, "No claim should be created when 503 is returned"


# ---------------------------------------------------------------------------
# GET /claims/{claim_id}/stream
# ---------------------------------------------------------------------------


class TestStreamClaimUpdates:
    """Tests for GET /claims/{claim_id}/stream SSE endpoint."""

    def test_existing_claim_returns_event_stream(self, client):
        """Stream endpoint returns text/event-stream content for an existing claim."""
        resp = client.get("/api/v1/claims/CLM-TEST001/stream")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        assert "Cache-Control" in resp.headers
        assert "data:" in resp.text
        assert "CLM-TEST001" in resp.text

    def test_unknown_claim_returns_404(self, client):
        """Stream endpoint returns 404 for a non-existent claim ID."""
        resp = client.get("/api/v1/claims/CLM-DOESNOTEXIST/stream")
        assert resp.status_code == 404

    def test_stream_sends_done_event(self, client):
        """Stream terminates with a done event for claims in a non-pending/processing status."""
        # CLM-TEST001 has status 'open', which is not 'pending' or 'processing',
        # so the SSE generator emits a final done event immediately.
        resp = client.get("/api/v1/claims/CLM-TEST001/stream")
        assert resp.status_code == 200
        content = resp.text
        assert "done" in content


# ---------------------------------------------------------------------------
# POST /claims/{claim_id}/reprocess
# ---------------------------------------------------------------------------


class TestReprocessClaim:
    """Tests for POST /claims/{claim_id}/reprocess."""

    @pytest.fixture(autouse=True)
    def _mock_wf(self, monkeypatch):
        """Patch run_claim_workflow so reprocess tests never hit a real LLM."""
        import claim_agent.api.routes.claims_workflow as wf_mod

        monkeypatch.setattr(
            wf_mod, "run_claim_workflow", lambda *a, **kw: {"claim_id": "CLM-TEST001"}
        )

    def test_reprocess_existing_claim_returns_200(self, client):
        """Supervisor can reprocess an existing claim."""
        resp = client.post("/api/v1/claims/CLM-TEST001/reprocess")
        assert resp.status_code == 200

    def test_reprocess_unknown_claim_returns_404(self, client):
        """Reprocessing a non-existent claim returns 404."""
        resp = client.post("/api/v1/claims/CLM-DOESNOTEXIST/reprocess")
        assert resp.status_code == 404

    def test_reprocess_invalid_from_stage_returns_400(self, client):
        """Reprocessing with an invalid from_stage returns 400."""
        resp = client.post(
            "/api/v1/claims/CLM-TEST001/reprocess",
            params={"from_stage": "nonexistent_stage"},
        )
        assert resp.status_code == 400
        assert "from_stage must be one of" in resp.json()["detail"]
