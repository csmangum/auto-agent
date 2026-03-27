"""Tests for party management and portal token routes defined in claims_parties.py.

Covers:
- PATCH /claims/{claim_id}/parties/{party_id}/consent
- POST  /claims/{claim_id}/party-relationships
- DELETE /claims/{claim_id}/party-relationships/{relationship_id}
- POST  /claims/{claim_id}/portal-token
- POST  /claims/{claim_id}/repair-shop-portal-token
- POST  /claims/{claim_id}/repair-shop-assignment
- GET   /claims/{claim_id}/repair-shop-assignments
- DELETE /claims/{claim_id}/repair-shop-assignment/{shop_id}
- POST  /claims/{claim_id}/third-party-portal-token
"""

import pytest
from fastapi.testclient import TestClient

from claim_agent.config import reload_settings


def _auth_headers(key: str) -> dict:
    return {"X-API-Key": key}


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


@pytest.fixture()
def client():
    """Test client wired to the FastAPI application."""
    from claim_agent.api.server import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CLAIM_ID = "CLM-TEST001"
PARTIAL_LOSS_CLAIM_ID = "CLM-TEST005"  # claim_type=partial_loss, has a witness party


# ---------------------------------------------------------------------------
# PATCH /claims/{claim_id}/parties/{party_id}/consent
# ---------------------------------------------------------------------------


class TestUpdatePartyConsent:
    def test_returns_200_with_consent_status(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        # First add a party to CLM-TEST001
        from claim_agent.context import ClaimContext
        from claim_agent.db.database import get_db_path
        from claim_agent.models.party import ClaimPartyInput

        ctx = ClaimContext.from_defaults(db_path=get_db_path())
        party_id = ctx.repo.add_claim_party(
            CLAIM_ID,
            ClaimPartyInput(party_type="claimant", name="Test Party", email="test@example.com"),
        )
        resp = client.patch(
            f"/api/v1/claims/{CLAIM_ID}/parties/{party_id}/consent",
            json={"consent_status": "granted"},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == CLAIM_ID
        assert data["party_id"] == party_id
        assert data["consent_status"] == "granted"

    def test_invalid_consent_status_returns_422(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.patch(
            f"/api/v1/claims/{CLAIM_ID}/parties/1/consent",
            json={"consent_status": "invalid_status"},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 422

    def test_unknown_party_returns_404(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.patch(
            f"/api/v1/claims/{CLAIM_ID}/parties/99999/consent",
            json={"consent_status": "revoked"},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 404

    def test_missing_auth_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.patch(
            f"/api/v1/claims/{CLAIM_ID}/parties/1/consent",
            json={"consent_status": "granted"},
        )
        assert resp.status_code == 401

    def test_unknown_claim_returns_404(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.patch(
            "/api/v1/claims/NO-SUCH-CLAIM/parties/1/consent",
            json={"consent_status": "granted"},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /claims/{claim_id}/party-relationships
# ---------------------------------------------------------------------------


class TestCreatePartyRelationship:
    def _add_two_parties(self, claim_id: str) -> tuple[int, int]:
        from claim_agent.context import ClaimContext
        from claim_agent.db.database import get_db_path
        from claim_agent.models.party import ClaimPartyInput

        ctx = ClaimContext.from_defaults(db_path=get_db_path())
        p1 = ctx.repo.add_claim_party(claim_id, ClaimPartyInput(party_type="claimant", name="Alice"))
        p2 = ctx.repo.add_claim_party(claim_id, ClaimPartyInput(party_type="attorney", name="Bob"))
        return p1, p2

    def test_creates_relationship_returns_201(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        p1, p2 = self._add_two_parties(CLAIM_ID)
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/party-relationships",
            json={
                "from_party_id": p1,
                "to_party_id": p2,
                "relationship_type": "represented_by",
            },
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["claim_id"] == CLAIM_ID
        assert data["from_party_id"] == p1
        assert data["to_party_id"] == p2
        assert data["relationship_type"] == "represented_by"
        assert "id" in data

    def test_missing_auth_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/party-relationships",
            json={"from_party_id": 1, "to_party_id": 2, "relationship_type": "represented_by"},
        )
        assert resp.status_code == 401

    def test_invalid_relationship_type_returns_422(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/party-relationships",
            json={
                "from_party_id": 1,
                "to_party_id": 2,
                "relationship_type": "not_a_valid_type",
            },
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# DELETE /claims/{claim_id}/party-relationships/{relationship_id}
# ---------------------------------------------------------------------------


class TestDeletePartyRelationship:
    def test_deletes_relationship_returns_204(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        from claim_agent.context import ClaimContext
        from claim_agent.db.database import get_db_path
        from claim_agent.models.party import ClaimPartyInput

        ctx = ClaimContext.from_defaults(db_path=get_db_path())
        p1 = ctx.repo.add_claim_party(CLAIM_ID, ClaimPartyInput(party_type="claimant", name="Alice"))
        p2 = ctx.repo.add_claim_party(CLAIM_ID, ClaimPartyInput(party_type="attorney", name="Bob"))
        rel_id = ctx.repo.add_claim_party_relationship(CLAIM_ID, p1, p2, "represented_by")

        resp = client.delete(
            f"/api/v1/claims/{CLAIM_ID}/party-relationships/{rel_id}",
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 204

    def test_unknown_relationship_returns_404(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.delete(
            f"/api/v1/claims/{CLAIM_ID}/party-relationships/99999",
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 404

    def test_missing_auth_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.delete(
            f"/api/v1/claims/{CLAIM_ID}/party-relationships/1",
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /claims/{claim_id}/portal-token  (claimant portal)
# ---------------------------------------------------------------------------


class TestCreatePortalToken:
    def test_portal_token_disabled_returns_503(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "false")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/portal-token",
            json={},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 503

    def test_portal_token_enabled_returns_token(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "true")
        monkeypatch.setenv("PORTAL_JWT_SECRET", "test-secret-at-least-32-characters-long!")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/portal-token",
            json={"email": "claimant@example.com"},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == CLAIM_ID
        assert "token" in data
        assert data["token"]

    def test_missing_auth_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/portal-token",
            json={},
        )
        assert resp.status_code == 401

    def test_unknown_claim_returns_404(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "true")
        monkeypatch.setenv("PORTAL_JWT_SECRET", "test-secret-at-least-32-characters-long!")
        reload_settings()
        resp = client.post(
            "/api/v1/claims/NO-SUCH-CLAIM/portal-token",
            json={},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /claims/{claim_id}/repair-shop-portal-token
# ---------------------------------------------------------------------------


class TestCreateRepairShopPortalToken:
    def test_non_partial_loss_claim_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "true")
        monkeypatch.setenv("REPAIR_SHOP_PORTAL_JWT_SECRET", "repair-secret-at-least-32-chars-long!")
        reload_settings()
        # CLM-TEST001 is claim_type=new, not partial_loss
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-portal-token",
            json={},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 400
        assert "partial_loss" in resp.json()["detail"]

    def test_repair_shop_portal_disabled_returns_503(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "false")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{PARTIAL_LOSS_CLAIM_ID}/repair-shop-portal-token",
            json={},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 503

    def test_partial_loss_claim_returns_token(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("REPAIR_SHOP_PORTAL_ENABLED", "true")
        monkeypatch.setenv("REPAIR_SHOP_PORTAL_JWT_SECRET", "repair-secret-at-least-32-chars-long!")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{PARTIAL_LOSS_CLAIM_ID}/repair-shop-portal-token",
            json={"shop_id": "SHOP-001"},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == PARTIAL_LOSS_CLAIM_ID
        assert "token" in data
        assert data["token"]

    def test_missing_auth_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{PARTIAL_LOSS_CLAIM_ID}/repair-shop-portal-token",
            json={},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /claims/{claim_id}/repair-shop-assignment
# GET  /claims/{claim_id}/repair-shop-assignments
# DELETE /claims/{claim_id}/repair-shop-assignment/{shop_id}
# ---------------------------------------------------------------------------


class TestRepairShopAssignments:
    def test_assign_repair_shop_returns_201(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment",
            json={"shop_id": "SHOP-XYZ", "notes": "Preferred shop"},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["shop_id"] == "SHOP-XYZ"
        assert data["claim_id"] == CLAIM_ID

    def test_duplicate_assignment_returns_409(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        client.post(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment",
            json={"shop_id": "SHOP-DUP"},
            headers=_auth_headers("sk-adj"),
        )
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment",
            json={"shop_id": "SHOP-DUP"},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 409

    def test_list_repair_shop_assignments_returns_200(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        post_resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment",
            json={"shop_id": "SHOP-LIST"},
            headers=_auth_headers("sk-adj"),
        )
        assert post_resp.status_code == 201
        resp = client.get(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignments",
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == CLAIM_ID
        assert isinstance(data["assignments"], list)
        shop_ids = [a["shop_id"] for a in data["assignments"]]
        assert "SHOP-LIST" in shop_ids

    def test_list_repair_shop_assignments_empty(self, client, monkeypatch):
        # Each test gets a fresh seeded DB via the autouse _use_seeded_db fixture,
        # so no prior assignments exist for CLAIM_ID at this point.
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.get(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignments",
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["assignments"] == []

    def test_remove_repair_shop_assignment_returns_200(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        client.post(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment",
            json={"shop_id": "SHOP-DEL"},
            headers=_auth_headers("sk-adj"),
        )
        resp = client.delete(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment/SHOP-DEL",
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_remove_nonexistent_assignment_returns_404(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.delete(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment/NO-SUCH-SHOP",
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 404

    def test_missing_auth_assign_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment",
            json={"shop_id": "SHOP-XYZ"},
        )
        assert resp.status_code == 401

    def test_missing_auth_list_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.get(f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignments")
        assert resp.status_code == 401

    def test_missing_auth_remove_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.delete(
            f"/api/v1/claims/{CLAIM_ID}/repair-shop-assignment/SHOP-XYZ"
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /claims/{claim_id}/third-party-portal-token
# ---------------------------------------------------------------------------


class TestCreateThirdPartyPortalToken:
    def test_third_party_portal_disabled_returns_503(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "false")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{PARTIAL_LOSS_CLAIM_ID}/third-party-portal-token",
            json={"party_id": 1},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 503

    def test_invalid_party_id_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
        monkeypatch.setenv(
            "THIRD_PARTY_PORTAL_JWT_SECRET", "third-party-secret-at-least-32-chars!"
        )
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{PARTIAL_LOSS_CLAIM_ID}/third-party-portal-token",
            json={"party_id": 99999},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 400
        assert "not a party" in resp.json()["detail"]

    def test_ineligible_party_type_returns_400(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
        monkeypatch.setenv(
            "THIRD_PARTY_PORTAL_JWT_SECRET", "third-party-secret-at-least-32-chars!"
        )
        reload_settings()
        # Add a 'claimant' party (not eligible for third-party portal)
        from claim_agent.context import ClaimContext
        from claim_agent.db.database import get_db_path
        from claim_agent.models.party import ClaimPartyInput

        ctx = ClaimContext.from_defaults(db_path=get_db_path())
        party_id = ctx.repo.add_claim_party(
            PARTIAL_LOSS_CLAIM_ID,
            ClaimPartyInput(party_type="claimant", name="Not Eligible"),
        )
        resp = client.post(
            f"/api/v1/claims/{PARTIAL_LOSS_CLAIM_ID}/third-party-portal-token",
            json={"party_id": party_id},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 400
        assert "Third-party portal tokens" in resp.json()["detail"]

    def test_eligible_witness_party_returns_token(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
        monkeypatch.setenv(
            "THIRD_PARTY_PORTAL_JWT_SECRET", "third-party-secret-at-least-32-chars!"
        )
        reload_settings()
        # Get the seeded witness party on CLM-TEST005
        from claim_agent.context import ClaimContext
        from claim_agent.db.database import get_db_path

        ctx = ClaimContext.from_defaults(db_path=get_db_path())
        parties = ctx.repo.get_claim_parties(PARTIAL_LOSS_CLAIM_ID)
        witness = next(p for p in parties if p.get("party_type") == "witness")
        resp = client.post(
            f"/api/v1/claims/{PARTIAL_LOSS_CLAIM_ID}/third-party-portal-token",
            json={"party_id": witness["id"]},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == PARTIAL_LOSS_CLAIM_ID
        assert "token" in data
        assert data["token"]

    def test_missing_auth_returns_401(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        reload_settings()
        resp = client.post(
            f"/api/v1/claims/{PARTIAL_LOSS_CLAIM_ID}/third-party-portal-token",
            json={"party_id": 1},
        )
        assert resp.status_code == 401

    def test_unknown_claim_returns_404(self, client, monkeypatch):
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
        monkeypatch.setenv(
            "THIRD_PARTY_PORTAL_JWT_SECRET", "third-party-secret-at-least-32-chars!"
        )
        reload_settings()
        resp = client.post(
            "/api/v1/claims/NO-SUCH-CLAIM/third-party-portal-token",
            json={"party_id": 1},
            headers=_auth_headers("sk-adj"),
        )
        assert resp.status_code == 404
