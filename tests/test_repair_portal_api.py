"""Tests for repair shop portal routes (/api/repair-portal/*) and token minting."""

import pytest
from fastapi.testclient import TestClient

from claim_agent.config import reload_settings


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    from claim_agent.api.server import app

    return TestClient(app)


@pytest.fixture
def repair_portal_on(monkeypatch):
    monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "true")
    reload_settings()
    yield
    monkeypatch.delenv("REPAIR_SHOP_PORTAL_ENABLED", raising=False)
    reload_settings()


@pytest.mark.usefixtures("repair_portal_on")
class TestRepairShopPortal:
    def test_mint_token_disabled_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("REPAIR_SHOP_PORTAL_ENABLED", raising=False)
        reload_settings()
        resp = client.post("/api/claims/CLM-TEST005/repair-shop-portal-token", json={})
        assert resp.status_code == 503
        monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "true")
        reload_settings()

    def test_mint_token_non_partial_loss_returns_400(self, client):
        resp = client.post("/api/claims/CLM-TEST001/repair-shop-portal-token", json={})
        assert resp.status_code == 400
        assert "partial_loss" in resp.json()["detail"].lower()

    def test_mint_token_success(self, client):
        resp = client.post(
            "/api/claims/CLM-TEST005/repair-shop-portal-token",
            json={"shop_id": "SHOP-E2E"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST005"
        assert "token" in data
        assert len(data["token"]) > 20

    def test_portal_get_claim_without_token_401(self, client):
        resp = client.get("/api/repair-portal/claims/CLM-TEST005")
        assert resp.status_code == 401

    def test_portal_get_claim_invalid_token_401(self, client):
        resp = client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"X-Repair-Shop-Access-Token": "not-a-valid-token"},
        )
        assert resp.status_code == 401

    def test_portal_get_claim_success(self, client):
        mint = client.post("/api/claims/CLM-TEST005/repair-shop-portal-token", json={})
        token = mint.json()["token"]
        resp = client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"X-Repair-Shop-Access-Token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "CLM-TEST005"
        assert "follow_up_messages" in body
        assert "document_requests" in body

    def test_portal_repair_status_post_and_get(self, client):
        mint = client.post("/api/claims/CLM-TEST005/repair-shop-portal-token", json={"shop_id": "S1"})
        token = mint.json()["token"]
        h = {"X-Repair-Shop-Access-Token": token}
        post = client.post(
            "/api/repair-portal/claims/CLM-TEST005/repair-status",
            headers=h,
            json={"status": "received", "notes": "Dropped off"},
        )
        assert post.status_code == 200
        get = client.get("/api/repair-portal/claims/CLM-TEST005/repair-status", headers=h)
        assert get.status_code == 200
        assert get.json()["latest"]["status"] == "received"
        assert get.json()["latest"]["shop_id"] == "S1"

    def test_portal_disabled_returns_503(self, client, monkeypatch):
        mint = client.post("/api/claims/CLM-TEST005/repair-shop-portal-token", json={})
        token = mint.json()["token"]
        monkeypatch.delenv("REPAIR_SHOP_PORTAL_ENABLED", raising=False)
        reload_settings()
        resp = client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"X-Repair-Shop-Access-Token": token},
        )
        assert resp.status_code == 503
