"""Tests for the unified external portal API.

Covers:
- GET /api/portal/auth/role (role detection from various credentials)
- POST /api/portal/auth/login (repair shop user login)
- Cross-privilege isolation: claimant creds cannot access repair-shop routes
  and repair-shop creds cannot access claimant-only routes
- Unified token (external_portal_tokens) round-trip
"""

import pytest
from fastapi.testclient import TestClient

from claim_agent.config import reload_settings
from claim_agent.services.portal_verification import create_claim_access_token
from claim_agent.services.repair_shop_portal_tokens import create_repair_shop_access_token
from claim_agent.services.unified_portal_tokens import (
    create_unified_portal_token,
    revoke_unified_portal_token,
    verify_unified_portal_token,
)


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    yield


@pytest.fixture(autouse=True)
def _enable_portals(monkeypatch):
    monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "true")
    monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "true")
    monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
    monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
    reload_settings()
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


# ---------------------------------------------------------------------------
# GET /api/portal/auth/role
# ---------------------------------------------------------------------------


class TestDetectPortalRole:
    def test_role_returns_401_without_credentials(self, client):
        resp = client.get("/api/portal/auth/role")
        assert resp.status_code == 401

    def test_role_claimant_via_policy_vin(self, client):
        """Policy + VIN → role=claimant."""
        resp = client.get(
            "/api/portal/auth/role",
            headers={"X-Policy-Number": "POL-001", "X-Vin": "1HGBH41JXMN109186"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "claimant"
        assert "CLM-TEST001" in body["claim_ids"]
        assert body["redirect"] == "/portal/claims"

    def test_role_claimant_via_token(self, client, monkeypatch):
        """Claimant access token → role=claimant."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "token")
        reload_settings()
        raw_token = create_claim_access_token("CLM-TEST001")
        resp = client.get(
            "/api/portal/auth/role",
            headers={"X-Claim-Access-Token": raw_token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "claimant"
        assert "CLM-TEST001" in body["claim_ids"]

    def test_role_repair_shop_via_legacy_token(self, client):
        """Repair shop per-claim token → role=repair_shop."""
        shop_token = create_repair_shop_access_token("CLM-TEST005", shop_id="SHOP-UNIT")
        resp = client.get(
            "/api/portal/auth/role",
            headers={
                "X-Repair-Shop-Access-Token": shop_token,
                "X-Claim-Id": "CLM-TEST005",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "repair_shop"
        assert "CLM-TEST005" in body["claim_ids"]
        assert body["shop_id"] == "SHOP-UNIT"
        assert body["redirect"] == "/repair-portal/claims"

    def test_role_unified_token_claimant(self, client):
        """Unified token with role=claimant → verified role."""
        raw = create_unified_portal_token(
            "claimant",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
        )
        resp = client.get(
            "/api/portal/auth/role",
            headers={"X-Portal-Token": raw},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "claimant"
        assert body["claim_ids"] == ["CLM-TEST001"]
        assert "read_claim" in body["scopes"]

    def test_role_unified_token_repair_shop(self, client):
        """Unified token with role=repair_shop → verified role."""
        raw = create_unified_portal_token(
            "repair_shop",
            scopes=["read_claim", "update_repair_status"],
            claim_id="CLM-TEST005",
            shop_id="SHOP-UNIFIED",
        )
        resp = client.get(
            "/api/portal/auth/role",
            headers={"X-Portal-Token": raw},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "repair_shop"
        assert body["claim_ids"] == ["CLM-TEST005"]
        assert body["shop_id"] == "SHOP-UNIFIED"

    def test_role_unified_token_invalid(self, client):
        """Tampered/invalid unified token → 401."""
        resp = client.get(
            "/api/portal/auth/role",
            headers={"X-Portal-Token": "not-a-valid-token"},
        )
        assert resp.status_code == 401

    def test_unified_token_503_when_claimant_portal_disabled(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "false")
        reload_settings()
        raw = create_unified_portal_token("claimant", claim_id="CLM-TEST001")
        resp = client.get("/api/portal/auth/role", headers={"X-Portal-Token": raw})
        assert resp.status_code == 503

    def test_unified_token_503_when_repair_portal_disabled(self, client, monkeypatch):
        monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "false")
        reload_settings()
        raw = create_unified_portal_token(
            "repair_shop",
            claim_id="CLM-TEST005",
            shop_id="SHOP-X",
        )
        resp = client.get("/api/portal/auth/role", headers={"X-Portal-Token": raw})
        assert resp.status_code == 503

    def test_unified_token_503_when_third_party_portal_disabled(self, client, monkeypatch):
        monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "false")
        reload_settings()
        raw = create_unified_portal_token("tpa", claim_id="CLM-TEST001")
        resp = client.get("/api/portal/auth/role", headers={"X-Portal-Token": raw})
        assert resp.status_code == 503

    def test_role_repair_shop_invalid_token(self, client):
        """Invalid repair shop token → 401."""
        resp = client.get(
            "/api/portal/auth/role",
            headers={
                "X-Repair-Shop-Access-Token": "bad-token",
                "X-Claim-Id": "CLM-TEST005",
            },
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Cross-privilege isolation
# ---------------------------------------------------------------------------


class TestCrossPrivilegeIsolation:
    """Verify that claimant creds cannot access repair-shop endpoints
    and that repair-shop tokens cannot access claimant-only endpoints."""

    def test_claimant_token_cannot_access_repair_portal(self, client):
        """A valid claimant access token should NOT grant access to /api/repair-portal/."""
        raw_token = create_claim_access_token("CLM-TEST005")
        # Repair portal requires X-Repair-Shop-Access-Token, not claimant token.
        resp = client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"X-Claim-Access-Token": raw_token},
        )
        assert resp.status_code == 401

    def test_repair_shop_token_cannot_access_claimant_portal(self, client):
        """A valid repair-shop access token should NOT grant access to /api/portal/claims/."""
        shop_token = create_repair_shop_access_token("CLM-TEST005", shop_id="SHOP-X")
        resp = client.get(
            "/api/portal/claims",
            headers={"X-Repair-Shop-Access-Token": shop_token},
        )
        # Claimant portal does not recognise X-Repair-Shop-Access-Token → 401
        assert resp.status_code == 401

    def test_claimant_policy_vin_cannot_access_repair_portal(self, client):
        """Policy+VIN claimant credentials should NOT grant access to repair-portal."""
        resp = client.get(
            "/api/repair-portal/claims/CLM-TEST001",
            headers={"X-Policy-Number": "POL-001", "X-Vin": "1HGBH41JXMN109186"},
        )
        assert resp.status_code == 401

    def test_unified_claimant_token_cannot_access_repair_portal(self, client):
        """A unified claimant token should NOT satisfy repair-shop auth."""
        raw = create_unified_portal_token(
            "claimant",
            claim_id="CLM-TEST005",
        )
        resp = client.get(
            "/api/repair-portal/claims/CLM-TEST005",
            headers={"X-Claim-Access-Token": raw},
        )
        # Repair portal checks X-Repair-Shop-Access-Token, not X-Claim-Access-Token
        assert resp.status_code == 401

    def test_unified_repair_token_cannot_access_wrong_claim(self, client):
        """A unified repair-shop token for CLM-TEST005 should NOT grant /portal/auth/role
        for a different claim when queried via the unified session dep."""
        raw = create_unified_portal_token(
            "repair_shop",
            claim_id="CLM-TEST005",
            shop_id="SHOP-X",
        )
        resp = client.get(
            "/api/portal/auth/role",
            headers={"X-Portal-Token": raw},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Must only see the specific claim in the token, not others
        assert body["claim_ids"] == ["CLM-TEST005"]
        assert "CLM-TEST001" not in body["claim_ids"]


# ---------------------------------------------------------------------------
# POST /api/portal/auth/login (unified repair-shop login)
# ---------------------------------------------------------------------------


class TestUnifiedShopLogin:
    def test_login_disabled_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("REPAIR_SHOP_PORTAL_ENABLED", raising=False)
        reload_settings()
        resp = client.post(
            "/api/portal/auth/login",
            json={"email": "shop@example.com", "password": "pw"},
        )
        assert resp.status_code == 503

    def test_login_invalid_credentials_returns_401(self, client):
        resp = client.post(
            "/api/portal/auth/login",
            json={"email": "noone@example.com", "password": "wrong"},
        )
        assert resp.status_code == 401

    def test_login_response_shape(self, client, monkeypatch):
        """Successful login response includes role and redirect fields.

        Requires JWT_SECRET and a seeded shop user.  Explicitly sets
        JWT_SECRET so the test is deterministic rather than silently skipping.
        """
        from claim_agent.db.repair_shop_user_repository import RepairShopUserRepository

        monkeypatch.setenv("JWT_SECRET", "test-secret-for-login-shape-32chars!")
        reload_settings()
        repo = RepairShopUserRepository()
        try:
            repo.create_shop_user(
                shop_id="SHOP-LOGIN-TEST",
                email="logintest@example.com",
                password="testpassword123",
            )
        except ValueError:
            pass  # already exists
        resp = client.post(
            "/api/portal/auth/login",
            json={"email": "logintest@example.com", "password": "testpassword123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "repair_shop"
        assert body["redirect"] == "/repair-portal/claims"
        assert "access_token" in body
        assert body["token_type"] == "bearer"


# ---------------------------------------------------------------------------
# Token revocation
# ---------------------------------------------------------------------------


class TestTokenRevocation:
    def test_revoke_valid_token(self, client):
        """Revoking a token should make it fail verification."""
        raw = create_unified_portal_token(
            "claimant",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
        )
        rec = verify_unified_portal_token(raw)
        assert rec is not None

        assert revoke_unified_portal_token(raw) is True

        rec_after = verify_unified_portal_token(raw)
        assert rec_after is None

    def test_revoke_invalid_token_returns_false(self):
        """Revoking a non-existent token should return False."""
        assert revoke_unified_portal_token("non-existent-token") is False

    def test_revoke_empty_token(self):
        assert revoke_unified_portal_token("") is False
        assert revoke_unified_portal_token("   ") is False

    def test_revoked_token_rejected_by_api(self, client):
        """A revoked unified token should get 401 from /api/portal/auth/role."""
        raw = create_unified_portal_token(
            "repair_shop",
            scopes=["read_claim"],
            claim_id="CLM-TEST005",
            shop_id="SHOP-REV",
        )
        resp = client.get(
            "/api/portal/auth/role",
            headers={"X-Portal-Token": raw},
        )
        assert resp.status_code == 200

        revoke_unified_portal_token(raw)

        resp2 = client.get(
            "/api/portal/auth/role",
            headers={"X-Portal-Token": raw},
        )
        assert resp2.status_code == 401

    def test_double_revoke_returns_false(self):
        """Revoking an already-revoked token should return False."""
        raw = create_unified_portal_token(
            "claimant",
            claim_id="CLM-TEST001",
        )
        assert revoke_unified_portal_token(raw) is True
        assert revoke_unified_portal_token(raw) is False


# ---------------------------------------------------------------------------
# TPA role
# ---------------------------------------------------------------------------


class TestTpaRole:
    def test_tpa_unified_token_role_detection(self, client):
        """Unified token with role=tpa returns correct role and redirect."""
        raw = create_unified_portal_token(
            "tpa",
            scopes=["read_claim"],
            claim_id="CLM-TEST001",
        )
        resp = client.get(
            "/api/portal/auth/role",
            headers={"X-Portal-Token": raw},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["role"] == "tpa"
        assert body["claim_ids"] == ["CLM-TEST001"]
        assert body["redirect"] == "/third-party-portal/claims"


# ---------------------------------------------------------------------------
# Scope validation
# ---------------------------------------------------------------------------


class TestScopeValidation:
    def test_invalid_scope_rejected_at_creation(self):
        """create_unified_portal_token rejects unknown scope strings."""
        with pytest.raises(ValueError, match="Invalid portal scopes"):
            create_unified_portal_token(
                "claimant",
                scopes=["read_claim", "admin_override"],
                claim_id="CLM-TEST001",
            )

    def test_create_requires_claim_id(self):
        with pytest.raises(ValueError, match="claim_id is required"):
            create_unified_portal_token("claimant")

    def test_create_repair_shop_requires_shop_id(self):
        with pytest.raises(ValueError, match="shop_id is required"):
            create_unified_portal_token("repair_shop", claim_id="CLM-TEST005")

    def test_issue_token_requires_bearer_and_adjuster_role(self, client, monkeypatch):
        """POST /api/portal/auth/issue-token uses CLAIMS_API_KEY auth and RBAC."""
        monkeypatch.setenv("API_KEYS", "")
        monkeypatch.setenv("CLAIMS_API_KEY", "issuer-key")
        monkeypatch.setenv("JWT_SECRET", "")
        reload_settings()
        payload = {
            "role": "claimant",
            "scopes": ["read_claim", "delete_everything"],
            "claim_id": "CLM-TEST001",
        }
        assert client.post("/api/portal/auth/issue-token", json=payload).status_code == 401
        assert (
            client.post(
                "/api/portal/auth/issue-token",
                json=payload,
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/portal/auth/issue-token",
                json=payload,
                headers={"Authorization": "Bearer issuer-key"},
            ).status_code
            == 422
        )

    def test_issue_token_insufficient_api_key_role(self, client, monkeypatch):
        monkeypatch.setenv("CLAIMS_API_KEY", "")
        monkeypatch.setenv("API_KEYS", "lowpriv:readonly")
        monkeypatch.setenv("JWT_SECRET", "")
        reload_settings()
        resp = client.post(
            "/api/portal/auth/issue-token",
            json={"role": "claimant", "claim_id": "CLM-TEST001"},
            headers={"Authorization": "Bearer lowpriv"},
        )
        assert resp.status_code == 403
