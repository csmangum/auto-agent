"""Tests for audit and history routes defined in claims_audit.py."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all API tests."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear rate limit buckets before each API test to avoid 429 in CI."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from claim_agent.api.server import app

    return TestClient(app)


# -------------------------------------------------------------------
# GET /claims/{claim_id}/history - get_claim_history
# -------------------------------------------------------------------


def test_claim_history(client):
    """get_claim_history returns audit log entries for a claim."""
    resp = client.get("/api/v1/claims/CLM-TEST001/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert "history" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert data["total"] >= 2
    assert len(data["history"]) >= 2


def test_claim_history_pagination(client):
    """get_claim_history respects limit and offset query parameters."""
    resp = client.get("/api/v1/claims/CLM-TEST001/history?limit=1&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert len(data["history"]) == 1


def test_claim_history_not_found(client):
    """get_claim_history returns 404 for unknown claim IDs."""
    resp = client.get("/api/v1/claims/CLM-DOESNOTEXIST/history")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# GET /claims/{claim_id}/fraud-filings - get_claim_fraud_filings
# -------------------------------------------------------------------


def test_get_claim_fraud_filings(client):
    """get_claim_fraud_filings returns fraud report filings for a claim."""
    resp = client.get("/api/v1/claims/CLM-TEST003/fraud-filings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST003"
    assert "filings" in data
    assert len(data["filings"]) == 2
    filing_types = {f["filing_type"] for f in data["filings"]}
    assert "state_bureau" in filing_types
    assert "nicb" in filing_types


def test_get_claim_fraud_filings_empty(client):
    """get_claim_fraud_filings returns empty list when no filings exist."""
    resp = client.get("/api/v1/claims/CLM-TEST001/fraud-filings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert data["filings"] == []


def test_get_claim_fraud_filings_not_found(client):
    """get_claim_fraud_filings returns 404 for unknown claim IDs."""
    resp = client.get("/api/v1/claims/CLM-DOESNOTEXIST/fraud-filings")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# GET /claims/{claim_id}/notes - get_claim_notes
# -------------------------------------------------------------------


def test_get_claim_notes(client):
    """get_claim_notes returns notes list for a claim."""
    resp = client.get("/api/v1/claims/CLM-TEST001/notes")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert "notes" in data
    assert isinstance(data["notes"], list)


def test_get_claim_notes_not_found(client):
    """get_claim_notes returns 404 for unknown claim IDs."""
    resp = client.get("/api/v1/claims/CLM-DOESNOTEXIST/notes")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/{claim_id}/notes - add_claim_note
# -------------------------------------------------------------------


def test_add_note(client):
    """add_claim_note creates a note and returns claim_id and actor_id."""
    payload = {"note": "Test note content", "actor_id": "adjuster_1"}
    resp = client.post("/api/v1/claims/CLM-TEST001/notes", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert data["actor_id"] == "adjuster_1"


def test_add_note_persisted(client):
    """add_claim_note note is retrievable via get_claim_notes after creation."""
    payload = {"note": "Persisted note", "actor_id": "workflow"}
    client.post("/api/v1/claims/CLM-TEST001/notes", json=payload)

    resp = client.get("/api/v1/claims/CLM-TEST001/notes")
    assert resp.status_code == 200
    notes = resp.json()["notes"]
    assert any(n["note"] == "Persisted note" for n in notes)


def test_add_note_blank_content_returns_422(client):
    """add_claim_note rejects blank note content with 422."""
    payload = {"note": "   ", "actor_id": "adjuster_1"}
    resp = client.post("/api/v1/claims/CLM-TEST001/notes", json=payload)
    assert resp.status_code == 422


def test_add_note_blank_actor_id_returns_422(client):
    """add_claim_note rejects blank actor_id with 422."""
    payload = {"note": "Valid note", "actor_id": "   "}
    resp = client.post("/api/v1/claims/CLM-TEST001/notes", json=payload)
    assert resp.status_code == 422


def test_add_note_not_found(client):
    """add_claim_note returns 404 for unknown claim IDs."""
    payload = {"note": "Some note", "actor_id": "workflow"}
    resp = client.post("/api/v1/claims/CLM-DOESNOTEXIST/notes", json=payload)
    assert resp.status_code == 404


# -------------------------------------------------------------------
# GET /claims/{claim_id}/workflows - get_claim_workflows
# -------------------------------------------------------------------


def test_get_claim_workflows(client):
    """get_claim_workflows returns workflow runs for a claim."""
    resp = client.get("/api/v1/claims/CLM-TEST001/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert "workflows" in data
    assert len(data["workflows"]) >= 1
    run = data["workflows"][0]
    assert run["claim_id"] == "CLM-TEST001"
    assert run["claim_type"] == "new"


def test_get_claim_workflows_empty(client):
    """get_claim_workflows returns empty list when no workflow runs exist."""
    resp = client.get("/api/v1/claims/CLM-TEST002/workflows")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST002"
    assert data["workflows"] == []


def test_get_claim_workflows_not_found(client):
    """get_claim_workflows returns 404 for unknown claim IDs."""
    resp = client.get("/api/v1/claims/CLM-DOESNOTEXIST/workflows")
    assert resp.status_code == 404
