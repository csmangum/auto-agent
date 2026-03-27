"""Tests for claims CRUD routes defined in claims_crud.py."""

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
# GET /claims - list_claims
# -------------------------------------------------------------------


def test_list_claims(client):
    """list_claims returns paginated claims with total count."""
    resp = client.get("/api/v1/claims")
    assert resp.status_code == 200
    data = resp.json()
    assert "claims" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert data["total"] == 5
    assert len(data["claims"]) == 5


def test_list_claims_filter_by_status(client):
    """list_claims filters by status query parameter."""
    resp = client.get("/api/v1/claims?status=open")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["claims"][0]["id"] == "CLM-TEST001"


def test_list_claims_filter_by_type(client):
    """list_claims filters by claim_type query parameter."""
    resp = client.get("/api/v1/claims?claim_type=fraud")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["claims"][0]["id"] == "CLM-TEST003"


def test_list_claims_excludes_archived_by_default(client):
    """list_claims excludes archived claims unless include_archived=true."""
    resp = client.get("/api/v1/claims")
    assert resp.status_code == 200
    claim_ids = [c["id"] for c in resp.json()["claims"]]
    assert "CLM-ARCHIVED" not in claim_ids


def test_list_claims_includes_archived_when_requested(client):
    """list_claims includes archived claims when include_archived=true."""
    resp = client.get("/api/v1/claims?include_archived=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert "CLM-ARCHIVED" in [c["id"] for c in data["claims"]]


def test_list_claims_invalid_sort_field_returns_400(client):
    """list_claims rejects unknown sort_by values with 400."""
    resp = client.get("/api/v1/claims?sort_by=nonexistent_field")
    assert resp.status_code == 400


def test_list_claims_invalid_sort_order_returns_400(client):
    """list_claims rejects sort_order values other than asc/desc with 400."""
    resp = client.get("/api/v1/claims?sort_order=random")
    assert resp.status_code == 400


def test_list_claims_pagination(client):
    """list_claims respects limit and offset parameters."""
    resp = client.get("/api/v1/claims?limit=2&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["claims"]) == 2
    assert data["total"] == 5


def test_list_claims_limit_zero_returns_422(client):
    """list_claims rejects limit=0 with 422."""
    resp = client.get("/api/v1/claims?limit=0")
    assert resp.status_code == 422


# -------------------------------------------------------------------
# GET /claims/{claim_id} - get_claim (get_claim_detail)
# -------------------------------------------------------------------


def test_get_claim(client):
    """get_claim returns full claim details including notes and parties."""
    resp = client.get("/api/v1/claims/CLM-TEST001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "CLM-TEST001"
    assert data["policy_number"] == "POL-001"
    assert data["status"] == "open"
    assert "notes" in data
    assert "follow_up_messages" in data
    assert "parties" in data
    assert "tasks" in data
    assert "subrogation_cases" in data


def test_get_claim_not_found(client):
    """get_claim returns 404 for unknown claim IDs."""
    resp = client.get("/api/v1/claims/CLM-DOESNOTEXIST")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# GET /claims/stats - get_claims_stats
# -------------------------------------------------------------------


def test_get_claims_stats(client):
    """get_claims_stats returns aggregate counts by status and type."""
    resp = client.get("/api/v1/claims/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total_claims" in data
    assert "by_status" in data
    assert "by_type" in data
    assert "total_audit_events" in data
    assert "total_workflow_runs" in data
    # seeded_temp_db seeds 7 claims (5 active + 1 archived + 1 purged)
    assert data["total_claims"] == 7


# -------------------------------------------------------------------
# GET /claims/review-queue - get_review_queue
# -------------------------------------------------------------------


def test_get_review_queue(client):
    """get_review_queue returns claims with needs_review status."""
    resp = client.get("/api/v1/claims/review-queue")
    assert resp.status_code == 200
    data = resp.json()
    assert "claims" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data


def test_get_review_queue_invalid_priority_returns_400(client):
    """get_review_queue rejects invalid priority values with 400."""
    resp = client.get("/api/v1/claims/review-queue?priority=invalid_priority")
    assert resp.status_code == 400


# -------------------------------------------------------------------
# GET /claims/{claim_id}/status - get_claim_status
# -------------------------------------------------------------------


def test_get_claim_status(client):
    """get_claim_status returns lightweight status payload."""
    resp = client.get("/api/v1/claims/CLM-TEST001/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert "status" in data
    assert "claim_type" in data
    assert "progress" in data
    assert isinstance(data["progress"], list)


def test_get_claim_status_not_found(client):
    """get_claim_status returns 404 for unknown claim IDs."""
    resp = client.get("/api/v1/claims/CLM-DOESNOTEXIST/status")
    assert resp.status_code == 404
