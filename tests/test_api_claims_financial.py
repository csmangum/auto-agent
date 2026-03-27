"""Tests for financial routes defined in claims_financial.py.

Covers: patch_claim_reserve, get_claim_reserve_history, get_claim_reserve_adequacy,
patch_claim_litigation_hold, get_claim_repair_status, update_claim_repair_status.
"""

import pytest
from fastapi.testclient import TestClient

from claim_agent.config import reload_settings


def _auth_headers(key: str) -> dict:
    return {"X-API-Key": key}


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all financial API tests."""
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


# CLM-TEST001 is a valid open (non-partial_loss) claim.
_CLAIM_ID = "CLM-TEST001"
# CLM-TEST005 is a partial_loss claim used for repair-status tests.
_PARTIAL_LOSS_CLAIM_ID = "CLM-TEST005"
_UNKNOWN_CLAIM = "CLM-DOESNOTEXIST"


# -------------------------------------------------------------------
# PATCH /claims/{claim_id}/reserve - patch_claim_reserve
# -------------------------------------------------------------------


def test_update_reserve(client):
    """patch_claim_reserve sets a reserve and returns claim_id + amount."""
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/reserve",
        json={"reserve_amount": 5000.0, "reason": "Initial assessment"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == _CLAIM_ID
    assert data["reserve_amount"] == 5000.0


def test_update_reserve_not_found(client):
    """patch_claim_reserve returns 404 for an unknown claim."""
    resp = client.patch(
        f"/api/v1/claims/{_UNKNOWN_CLAIM}/reserve",
        json={"reserve_amount": 1000.0},
    )
    assert resp.status_code == 404


def test_update_reserve_negative_amount_rejected(client):
    """patch_claim_reserve rejects negative reserve_amount with 422."""
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/reserve",
        json={"reserve_amount": -100.0},
    )
    assert resp.status_code == 422


def test_update_reserve_skip_authority_check_requires_admin(client, monkeypatch):
    """skip_authority_check=true is forbidden for non-admin roles."""
    monkeypatch.setenv("API_KEYS", "sk-adj:adjuster,sk-admin:admin")
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()

    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/reserve",
        json={"reserve_amount": 9999999.0, "skip_authority_check": True},
        headers=_auth_headers("sk-adj"),
    )
    assert resp.status_code == 403
    assert "admin" in resp.json()["detail"]


# -------------------------------------------------------------------
# GET /claims/{claim_id}/reserve-history - get_claim_reserve_history
# -------------------------------------------------------------------


def test_get_reserve_history_empty(client):
    """get_claim_reserve_history returns an empty list for a claim with no reserve."""
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/reserve-history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == _CLAIM_ID
    assert "history" in data
    assert isinstance(data["history"], list)
    assert data["limit"] == 50


def test_get_reserve_history_after_update(client):
    """get_claim_reserve_history reflects a reserve that was just set."""
    client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/reserve",
        json={"reserve_amount": 3000.0, "reason": "First estimate"},
    )
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/reserve-history")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["history"]) >= 1


def test_get_reserve_history_limit_param(client):
    """get_claim_reserve_history respects the limit query parameter."""
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/reserve-history?limit=10")
    assert resp.status_code == 200
    assert resp.json()["limit"] == 10


def test_get_reserve_history_not_found(client):
    """get_claim_reserve_history returns 404 for an unknown claim."""
    resp = client.get(f"/api/v1/claims/{_UNKNOWN_CLAIM}/reserve-history")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# GET /claims/{claim_id}/reserve/adequacy - get_claim_reserve_adequacy
# -------------------------------------------------------------------


def test_get_reserve_adequacy(client):
    """get_claim_reserve_adequacy returns adequacy result for a known claim."""
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/reserve/adequacy")
    assert resp.status_code == 200
    data = resp.json()
    # Response should contain warning information fields
    assert "warnings" in data or "warning_codes" in data or "adequate" in data


def test_get_reserve_adequacy_not_found(client):
    """get_claim_reserve_adequacy returns 404 for an unknown claim."""
    resp = client.get(f"/api/v1/claims/{_UNKNOWN_CLAIM}/reserve/adequacy")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# PATCH /claims/{claim_id}/litigation-hold - patch_claim_litigation_hold
# -------------------------------------------------------------------


def test_litigation_hold_set(client):
    """patch_claim_litigation_hold sets litigation hold to true."""
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/litigation-hold",
        json={"litigation_hold": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == _CLAIM_ID
    assert data["litigation_hold"] is True


def test_litigation_hold_clear(client):
    """patch_claim_litigation_hold clears litigation hold."""
    # First set it
    client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/litigation-hold",
        json={"litigation_hold": True},
    )
    # Then clear it
    resp = client.patch(
        f"/api/v1/claims/{_CLAIM_ID}/litigation-hold",
        json={"litigation_hold": False},
    )
    assert resp.status_code == 200
    assert resp.json()["litigation_hold"] is False


def test_litigation_hold_not_found(client):
    """patch_claim_litigation_hold returns 404 for an unknown claim."""
    resp = client.patch(
        f"/api/v1/claims/{_UNKNOWN_CLAIM}/litigation-hold",
        json={"litigation_hold": True},
    )
    assert resp.status_code == 404


# -------------------------------------------------------------------
# GET /claims/{claim_id}/repair-status - get_claim_repair_status
# -------------------------------------------------------------------


def test_repair_status_partial_loss(client):
    """get_claim_repair_status returns status data for a partial_loss claim."""
    resp = client.get(f"/api/v1/claims/{_PARTIAL_LOSS_CLAIM_ID}/repair-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["claim_id"] == _PARTIAL_LOSS_CLAIM_ID
    assert "latest" in data
    assert "history" in data
    assert "cycle_time_days" in data


def test_repair_status_non_partial_loss_rejected(client):
    """get_claim_repair_status returns 400 for non-partial_loss claims."""
    resp = client.get(f"/api/v1/claims/{_CLAIM_ID}/repair-status")
    assert resp.status_code == 400
    assert "partial_loss" in resp.json()["detail"]


def test_repair_status_not_found(client):
    """get_claim_repair_status returns 404 for an unknown claim."""
    resp = client.get(f"/api/v1/claims/{_UNKNOWN_CLAIM}/repair-status")
    assert resp.status_code == 404


# -------------------------------------------------------------------
# POST /claims/{claim_id}/repair-status - update_claim_repair_status
# -------------------------------------------------------------------


def test_update_repair_status(client):
    """update_claim_repair_status inserts a new status entry and returns its id."""
    resp = client.post(
        f"/api/v1/claims/{_PARTIAL_LOSS_CLAIM_ID}/repair-status",
        json={"status": "received", "shop_id": "SHOP-001", "authorization_id": "AUTH-001"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["repair_status_id"], int)


def test_update_repair_status_invalid_status(client):
    """update_claim_repair_status returns 400 for an unrecognised status value."""
    resp = client.post(
        f"/api/v1/claims/{_PARTIAL_LOSS_CLAIM_ID}/repair-status",
        json={"status": "not_a_valid_status"},
    )
    assert resp.status_code == 400
    assert "Invalid status" in resp.json()["detail"]


def test_update_repair_status_non_partial_loss_rejected(client):
    """update_claim_repair_status returns 400 for non-partial_loss claims."""
    resp = client.post(
        f"/api/v1/claims/{_CLAIM_ID}/repair-status",
        json={"status": "received"},
    )
    assert resp.status_code == 400
    assert "partial_loss" in resp.json()["detail"]


def test_update_repair_status_not_found(client):
    """update_claim_repair_status returns 404 for an unknown claim."""
    resp = client.post(
        f"/api/v1/claims/{_UNKNOWN_CLAIM}/repair-status",
        json={"status": "received"},
    )
    assert resp.status_code == 404


def test_update_repair_status_reflected_in_history(client):
    """Inserting a repair status is reflected in the subsequent GET."""
    client.post(
        f"/api/v1/claims/{_PARTIAL_LOSS_CLAIM_ID}/repair-status",
        json={"status": "repair", "shop_id": "SHOP-002", "authorization_id": "AUTH-002"},
    )
    resp = client.get(f"/api/v1/claims/{_PARTIAL_LOSS_CLAIM_ID}/repair-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["latest"] is not None
    assert data["latest"]["status"] == "repair"
