"""Tests for claims review workflow routes defined in claims_review.py.

Covers: assign, acknowledge, approve, reject, request-info, escalate-to-siu.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from claim_agent.config import reload_settings
from claim_agent.db.database import get_connection


def _auth_headers(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all claims-review API tests."""
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear rate limit buckets before each test to avoid 429 in CI."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from claim_agent.api.server import app

    return TestClient(app)


# CLM-TEST004 has status=needs_review and is used for most review route tests.
# CLM-TEST001 has status=open (used for 404/409 guard tests).


# -------------------------------------------------------------------
# PATCH /claims/{claim_id}/assign
# -------------------------------------------------------------------


def test_assign_claim(client):
    """assign_claim assigns an adjuster to a needs_review claim."""
    resp = client.patch(
        "/api/v1/claims/CLM-TEST004/assign",
        json={"assignee": "adjuster-review-1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST004"
    assert data["assignee"] == "adjuster-review-1"


def test_assign_claim_not_found(client):
    """assign_claim returns 404 for unknown claim IDs."""
    resp = client.patch(
        "/api/v1/claims/CLM-DOESNOTEXIST/assign",
        json={"assignee": "adjuster-1"},
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/{claim_id}/acknowledge
# -------------------------------------------------------------------


def test_acknowledge_claim(client, seeded_temp_db):
    """acknowledge_claim records UCSPA acknowledgment and returns acknowledged=True."""
    resp = client.post("/api/v1/claims/CLM-TEST001/acknowledge")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST001"
    assert data["acknowledged"] is True

    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository(db_path=seeded_temp_db)
    claim = repo.get_claim("CLM-TEST001")
    assert claim.get("acknowledged_at") is not None


def test_acknowledge_claim_not_found(client):
    """acknowledge_claim returns 404 for unknown claim IDs."""
    resp = client.post("/api/v1/claims/CLM-DOESNOTEXIST/acknowledge")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/{claim_id}/review/approve
# -------------------------------------------------------------------


def test_approve_claim(client, monkeypatch):
    """Supervisor can approve a needs_review claim and handback workflow runs."""
    import claim_agent.api.routes.claims_review as claims_review_mod

    monkeypatch.setenv("API_KEYS", "sk-sup:supervisor")
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()
    mock_result = {"claim_id": "CLM-TEST004", "status": "open", "claim_type": "new"}
    monkeypatch.setattr(claims_review_mod, "run_handback_workflow", lambda *a, **kw: mock_result)

    resp = client.post(
        "/api/v1/claims/CLM-TEST004/review/approve",
        headers=_auth_headers("sk-sup"),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST004"
    assert data["status"] == "open"


def test_approve_claim_requires_supervisor(client, monkeypatch):
    """Adjuster role is rejected with 403 on approve endpoint."""
    monkeypatch.setenv("API_KEYS", "sk-adj:adjuster,sk-sup:supervisor")
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()

    resp = client.post(
        "/api/v1/claims/CLM-TEST004/review/approve",
        headers={"X-API-Key": "sk-adj"},
    )
    assert resp.status_code == 403


def test_approve_claim_not_needs_review_returns_409(client, monkeypatch):
    """approve_review returns 409 when claim is not in needs_review status."""
    monkeypatch.setenv("API_KEYS", "sk-sup:supervisor")
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()

    # CLM-TEST001 has status "open", not needs_review
    resp = client.post(
        "/api/v1/claims/CLM-TEST001/review/approve",
        headers=_auth_headers("sk-sup"),
    )
    assert resp.status_code == 409
    assert "not in needs_review" in resp.json()["detail"]


def test_approve_claim_not_found(client, monkeypatch):
    """approve_review returns 404 for unknown claim IDs."""
    monkeypatch.setenv("API_KEYS", "sk-sup:supervisor")
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()

    resp = client.post(
        "/api/v1/claims/CLM-DOESNOTEXIST/review/approve",
        headers=_auth_headers("sk-sup"),
    )
    assert resp.status_code == 404


def test_approve_claim_invalid_payout_returns_422(client, monkeypatch):
    """ReviewerDecisionBody rejects negative confirmed_payout with 422."""
    import claim_agent.api.routes.claims_review as claims_review_mod

    monkeypatch.setenv("API_KEYS", "sk-sup:supervisor")
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()
    monkeypatch.setattr(claims_review_mod, "run_handback_workflow", lambda *a, **kw: {})

    resp = client.post(
        "/api/v1/claims/CLM-TEST004/review/approve",
        json={"reviewer_decision": {"confirmed_payout": -100}},
        headers=_auth_headers("sk-sup"),
    )
    assert resp.status_code == 422
    detail = str(resp.json()).lower()
    assert "confirmed_payout" in detail or "non-negative" in detail


# -------------------------------------------------------------------
# POST /claims/{claim_id}/review/reject
# -------------------------------------------------------------------


def test_reject_claim(client):
    """reject_review rejects a needs_review claim and returns status=denied."""
    resp = client.post(
        "/api/v1/claims/CLM-TEST004/review/reject",
        json={"reason": "Duplicate claim"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST004"
    assert data["status"] == "denied"


def test_reject_claim_not_found(client):
    """reject_review returns 404 for unknown claim IDs."""
    resp = client.post(
        "/api/v1/claims/CLM-DOESNOTEXIST/review/reject",
        json={"reason": "Not a valid claim"},
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/{claim_id}/review/request-info
# -------------------------------------------------------------------


def test_request_info_review(client):
    """request_info_review sets claim to pending_info status."""
    with get_connection() as conn:
        conn.execute(
            text("UPDATE claims SET status = :status WHERE id = :id"),
            {"status": "needs_review", "id": "CLM-TEST003"},
        )

    resp = client.post(
        "/api/v1/claims/CLM-TEST003/review/request-info",
        json={"note": "Please provide damage photos"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST003"
    assert data["status"] == "pending_info"


def test_request_info_review_not_found(client):
    """request_info_review returns 404 for unknown claim IDs."""
    resp = client.post(
        "/api/v1/claims/CLM-DOESNOTEXIST/review/request-info",
        json={"note": "More info needed"},
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/{claim_id}/review/escalate-to-siu
# -------------------------------------------------------------------


def test_escalate_to_siu(client):
    """escalate_to_siu sets claim to under_investigation status."""
    with get_connection() as conn:
        conn.execute(
            text("UPDATE claims SET status = :status WHERE id = :id"),
            {"status": "needs_review", "id": "CLM-TEST002"},
        )

    resp = client.post("/api/v1/claims/CLM-TEST002/review/escalate-to-siu")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == "CLM-TEST002"
    assert data["status"] == "under_investigation"


def test_escalate_to_siu_not_found(client):
    """escalate_to_siu returns 404 for unknown claim IDs."""
    resp = client.post("/api/v1/claims/CLM-DOESNOTEXIST/review/escalate-to-siu")
    assert resp.status_code == 404
