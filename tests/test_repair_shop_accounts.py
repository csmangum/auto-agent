"""Tests for repair shop multi-claim accounts.

Covers:
- Shop user creation and login (JWT)
- Claim assignment (adjuster creates, shop uses)
- Multi-claim inbox (GET /repair-portal/claims)
- Authorization boundaries: shop A cannot read shop B's claims
- Backward-compat: per-claim tokens still work
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from claim_agent.config import reload_settings

_ADMIN_KEY = "test-admin-key"
_ADJUSTER_KEY = "test-adjuster-key"
_API_KEYS_VALUE = f"{_ADMIN_KEY}:admin,{_ADJUSTER_KEY}:adjuster"
_JWT_SECRET = "a" * 32


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def repair_portal_and_auth(monkeypatch):
    """Enable repair portal and configure API keys + JWT secret."""
    monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "true")
    monkeypatch.setenv("JWT_SECRET", _JWT_SECRET)
    monkeypatch.setenv("API_KEYS", _API_KEYS_VALUE)
    reload_settings()
    yield
    monkeypatch.delenv("REPAIR_SHOP_PORTAL_ENABLED", raising=False)
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("API_KEYS", raising=False)
    reload_settings()


@pytest.fixture
def admin_client():
    """TestClient authenticated as admin."""
    from claim_agent.api.server import app

    return TestClient(app, headers={"Authorization": f"Bearer {_ADMIN_KEY}"})


@pytest.fixture
def adjuster_client():
    """TestClient authenticated as adjuster."""
    from claim_agent.api.server import app

    return TestClient(app, headers={"Authorization": f"Bearer {_ADJUSTER_KEY}"})


@pytest.fixture
def anon_client():
    """TestClient with no default auth headers (for portal endpoints)."""
    from claim_agent.api.server import app

    return TestClient(app)


@pytest.mark.usefixtures("repair_portal_and_auth")
class TestRepairShopUserAccounts:
    """Shop user account creation, login, and JWT verification."""

    def test_create_shop_user_admin_only(self, admin_client):
        resp = admin_client.post(
            "/api/repair-shop-users",
            json={"shop_id": "SHOP-A", "email": "shop@example.com", "password": "secure123"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["shop_id"] == "SHOP-A"
        assert data["email"] == "shop@example.com"
        assert "password_hash" not in data

    def test_duplicate_email_returns_409(self, admin_client):
        admin_client.post(
            "/api/repair-shop-users",
            json={"shop_id": "SHOP-A", "email": "dup@example.com", "password": "secure123"},
        )
        resp = admin_client.post(
            "/api/repair-shop-users",
            json={"shop_id": "SHOP-B", "email": "dup@example.com", "password": "secure456"},
        )
        assert resp.status_code == 409

    def test_login_returns_jwt(self, admin_client, anon_client):
        admin_client.post(
            "/api/repair-shop-users",
            json={"shop_id": "SHOP-A", "email": "login@example.com", "password": "secure123"},
        )
        resp = anon_client.post(
            "/api/repair-portal/auth/login",
            json={"email": "login@example.com", "password": "secure123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["shop_id"] == "SHOP-A"

    def test_login_wrong_password_401(self, admin_client, anon_client):
        admin_client.post(
            "/api/repair-shop-users",
            json={"shop_id": "SHOP-A", "email": "wrong@example.com", "password": "secure123"},
        )
        resp = anon_client.post(
            "/api/repair-portal/auth/login",
            json={"email": "wrong@example.com", "password": "badpass"},
        )
        assert resp.status_code == 401

    def test_login_unknown_email_401(self, anon_client):
        resp = anon_client.post(
            "/api/repair-portal/auth/login",
            json={"email": "nobody@example.com", "password": "any"},
        )
        assert resp.status_code == 401

    def test_login_disabled_returns_503(self, admin_client, anon_client, monkeypatch):
        admin_client.post(
            "/api/repair-shop-users",
            json={"shop_id": "SHOP-A", "email": "dis@example.com", "password": "secure123"},
        )
        monkeypatch.delenv("REPAIR_SHOP_PORTAL_ENABLED", raising=False)
        reload_settings()
        resp = anon_client.post(
            "/api/repair-portal/auth/login",
            json={"email": "dis@example.com", "password": "secure123"},
        )
        assert resp.status_code == 503


@pytest.mark.usefixtures("repair_portal_and_auth")
class TestClaimAssignment:
    """Adjuster assigns shop to claim; assignment listing and deletion."""

    def test_assign_shop_to_claim(self, adjuster_client):
        resp = adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-X"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST005"
        assert data["shop_id"] == "SHOP-X"

    def test_duplicate_assignment_returns_409(self, adjuster_client):
        adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-DUP"},
        )
        resp = adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-DUP"},
        )
        assert resp.status_code == 409

    def test_list_assignments_for_claim(self, adjuster_client):
        adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-LIST1"},
        )
        adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-LIST2"},
        )
        resp = adjuster_client.get("/api/claims/CLM-TEST005/repair-shop-assignments")
        assert resp.status_code == 200
        data = resp.json()
        shop_ids = {a["shop_id"] for a in data["assignments"]}
        assert "SHOP-LIST1" in shop_ids
        assert "SHOP-LIST2" in shop_ids

    def test_delete_assignment(self, adjuster_client):
        adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-DEL"},
        )
        resp = adjuster_client.delete(
            "/api/claims/CLM-TEST005/repair-shop-assignment/SHOP-DEL"
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_delete_nonexistent_assignment_404(self, adjuster_client):
        resp = adjuster_client.delete(
            "/api/claims/CLM-TEST005/repair-shop-assignment/SHOP-DOESNOTEXIST"
        )
        assert resp.status_code == 404


@pytest.mark.usefixtures("repair_portal_and_auth")
class TestMultiClaimInbox:
    """Shop user JWT → GET /repair-portal/claims lists assigned claims."""

    def _create_and_login(self, admin_client, anon_client, shop_id: str, email: str) -> str:
        """Create a shop user and return a bearer token."""
        admin_client.post(
            "/api/repair-shop-users",
            json={"shop_id": shop_id, "email": email, "password": "secure123"},
        )
        resp = anon_client.post(
            "/api/repair-portal/auth/login",
            json={"email": email, "password": "secure123"},
        )
        assert resp.status_code == 200, resp.json()
        return resp.json()["access_token"]

    def test_list_claims_requires_jwt(self, anon_client):
        resp = anon_client.get("/api/repair-portal/claims")
        assert resp.status_code == 401

    def test_list_claims_empty_when_none_assigned(self, admin_client, anon_client):
        token = self._create_and_login(admin_client, anon_client, "SHOP-EMPTY", "empty@example.com")
        resp = anon_client.get(
            "/api/repair-portal/claims",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claims"] == []
        assert data["shop_id"] == "SHOP-EMPTY"

    def test_list_claims_shows_assigned(self, admin_client, adjuster_client, anon_client):
        token = self._create_and_login(admin_client, anon_client, "SHOP-MULTI", "multi@example.com")
        adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-MULTI"},
        )
        adjuster_client.post(
            "/api/claims/CLM-TEST001/repair-shop-assignment",
            json={"shop_id": "SHOP-MULTI"},
        )
        resp = anon_client.get(
            "/api/repair-portal/claims",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        ids = {c["id"] for c in data["claims"]}
        assert "CLM-TEST005" in ids
        assert "CLM-TEST001" in ids

    def test_shop_a_cannot_see_shop_b_claims(self, admin_client, adjuster_client, anon_client):
        """Authorization boundary: shop A's JWT cannot see shop B's assigned claims."""
        token_a = self._create_and_login(admin_client, anon_client, "SHOP-AA", "aa@example.com")
        token_b = self._create_and_login(admin_client, anon_client, "SHOP-BB", "bb@example.com")
        adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-AA"},
        )
        adjuster_client.post(
            "/api/claims/CLM-TEST001/repair-shop-assignment",
            json={"shop_id": "SHOP-BB"},
        )

        resp_a = anon_client.get(
            "/api/repair-portal/claims",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        resp_b = anon_client.get(
            "/api/repair-portal/claims",
            headers={"Authorization": f"Bearer {token_b}"},
        )

        ids_a = {c["id"] for c in resp_a.json()["claims"]}
        ids_b = {c["id"] for c in resp_b.json()["claims"]}
        # Each shop only sees its own claims
        assert "CLM-TEST005" in ids_a
        assert "CLM-TEST001" not in ids_a
        assert "CLM-TEST001" in ids_b
        assert "CLM-TEST005" not in ids_b


@pytest.mark.usefixtures("repair_portal_and_auth")
class TestJWTSingleClaimAccess:
    """Shop user JWT can access single-claim endpoints if claim is assigned."""

    def _create_and_login(self, admin_client, anon_client, shop_id: str, email: str) -> str:
        admin_client.post(
            "/api/repair-shop-users",
            json={"shop_id": shop_id, "email": email, "password": "secure123"},
        )
        resp = anon_client.post(
            "/api/repair-portal/auth/login",
            json={"email": email, "password": "secure123"},
        )
        assert resp.status_code == 200, resp.json()
        return resp.json()["access_token"]

    def test_jwt_accesses_assigned_claim(self, admin_client, adjuster_client, anon_client):
        token = self._create_and_login(admin_client, anon_client, "SHOP-JWT1", "jwt1@example.com")
        adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-JWT1"},
        )
        resp = anon_client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "CLM-TEST005"

    def test_jwt_cannot_access_unassigned_claim(self, admin_client, anon_client):
        """Shop user JWT must be rejected for claims not assigned to their shop."""
        token = self._create_and_login(admin_client, anon_client, "SHOP-JWT2", "jwt2@example.com")
        # CLM-TEST005 is NOT assigned to SHOP-JWT2
        resp = anon_client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 403

    def test_shop_a_jwt_cannot_access_shop_b_claim(
        self, admin_client, adjuster_client, anon_client
    ):
        """SHOP-CC JWT must not access CLM-TEST005 assigned only to SHOP-DD."""
        token_c = self._create_and_login(admin_client, anon_client, "SHOP-CC", "cc@example.com")
        self._create_and_login(admin_client, anon_client, "SHOP-DD", "dd@example.com")
        # Assign CLM-TEST005 only to SHOP-DD
        adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-assignment",
            json={"shop_id": "SHOP-DD"},
        )
        resp = anon_client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"Authorization": f"Bearer {token_c}"},
        )
        assert resp.status_code == 403

    def test_per_claim_token_still_works(self, adjuster_client, anon_client):
        """Backward-compat: per-claim X-Repair-Shop-Access-Token still grants access."""
        mint = adjuster_client.post(
            "/api/claims/CLM-TEST005/repair-shop-portal-token", json={}
        )
        assert mint.status_code == 200, mint.json()
        token = mint.json()["token"]
        resp = anon_client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"X-Repair-Shop-Access-Token": token},
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == "CLM-TEST005"

