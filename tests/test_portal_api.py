"""Tests for the Claimant Portal API endpoints."""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from claim_agent.config import reload_settings
from claim_agent.db.database import get_connection
from claim_agent.services.portal_verification import create_claim_access_token


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all portal API tests."""
    yield


@pytest.fixture(autouse=True)
def _enable_portal(monkeypatch):
    """Enable the claimant portal for all portal API tests."""
    monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "true")
    reload_settings()
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


def _portal_policy_vin_headers(policy_number: str, vin: str) -> dict:
    """Headers for policy_vin verification mode."""
    return {
        "X-Policy-Number": policy_number,
        "X-Vin": vin,
    }


def _portal_token_headers(token: str) -> dict:
    """Headers for token verification mode."""
    return {"X-Claim-Access-Token": token}


# -------------------------------------------------------------------
# require_portal_session: 401 when invalid credentials
# -------------------------------------------------------------------


class TestPortalSession401:
    """Portal returns 401 when credentials are invalid or wrong mode."""

    def test_list_claims_401_without_headers(self, client, monkeypatch):
        """GET /portal/claims returns 401 when no verification headers provided."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.get("/api/portal/claims")
        assert resp.status_code == 401
        assert "Invalid" in resp.json().get("detail", "")

    def test_list_claims_401_invalid_policy_vin(self, client, monkeypatch):
        """GET /portal/claims returns 401 when policy+vin don't match any claim."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.get(
            "/api/portal/claims",
            headers=_portal_policy_vin_headers("POL-BAD", "VIN-BAD"),
        )
        assert resp.status_code == 401

    def test_list_claims_401_token_mode_ignores_policy_vin(self, client, monkeypatch):
        """In token mode, policy+vin are ignored; 401 when no token provided."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "token")
        reload_settings()
        # POL-001 + VIN for CLM-TEST001 exist in seeded DB, but token mode ignores them
        resp = client.get(
            "/api/portal/claims",
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 401

    def test_list_claims_401_invalid_token(self, client, monkeypatch):
        """GET /portal/claims returns 401 when token is invalid."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "token")
        reload_settings()
        resp = client.get(
            "/api/portal/claims",
            headers=_portal_token_headers("invalid-or-expired-token-xyz"),
        )
        assert resp.status_code == 401


# -------------------------------------------------------------------
# list_portal_claims returns only claimant's claims
# -------------------------------------------------------------------


class TestPortalListClaims:
    """Portal list claims returns only claimant's claims."""

    def test_list_claims_policy_vin_returns_matching_claims(self, client, monkeypatch):
        """GET /portal/claims with valid policy+vin returns only that claim."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.get(
            "/api/portal/claims",
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["claims"][0]["id"] == "CLM-TEST001"
        assert data["claims"][0]["policy_number"] == "POL-001"

    def test_list_claims_token_returns_only_token_claims(self, client, monkeypatch, seeded_temp_db):
        """GET /portal/claims with valid token returns only claims for that token."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "token")
        reload_settings()
        token = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        resp = client.get("/api/portal/claims", headers=_portal_token_headers(token))
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["claims"][0]["id"] == "CLM-TEST001"

    def test_list_claims_token_does_not_return_other_claims(
        self, client, monkeypatch, seeded_temp_db
    ):
        """Token for CLM-TEST001 does not return CLM-TEST002."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "token")
        reload_settings()
        token = create_claim_access_token("CLM-TEST001", db_path=seeded_temp_db)
        resp = client.get("/api/portal/claims", headers=_portal_token_headers(token))
        assert resp.status_code == 200
        claim_ids = [c["id"] for c in resp.json()["claims"]]
        assert "CLM-TEST001" in claim_ids
        assert "CLM-TEST002" not in claim_ids


# -------------------------------------------------------------------
# require_claimant_access: 404 when claim not in session
# -------------------------------------------------------------------


class TestPortalClaimantAccess404:
    """Portal returns 404 when claimant does not have access to the claim."""

    def test_get_claim_404_when_claim_not_in_session(self, client, monkeypatch):
        """GET /portal/claims/{id} returns 404 when claim not in claimant's session."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        # POL-001 has access to CLM-TEST001 only; CLM-TEST002 has POL-002
        resp = client.get(
            "/api/portal/claims/CLM-TEST002",
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 404
        assert "not found" in resp.json().get("detail", "").lower()

    def test_get_claim_history_404_when_claim_not_in_session(self, client, monkeypatch):
        """GET /portal/claims/{id}/history returns 404 when claim not in session."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.get(
            "/api/portal/claims/CLM-TEST002/history",
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 404


# -------------------------------------------------------------------
# Token creation and verification flow
# -------------------------------------------------------------------


class TestPortalTokenCreation:
    """Token creation (adjuster-only) and verification."""

    def test_create_portal_token_requires_adjuster(self, client, monkeypatch):
        """POST /claims/{id}/portal-token returns 401 without auth when auth required."""
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        reload_settings()
        resp = client.post("/api/claims/CLM-TEST001/portal-token", json={})
        assert resp.status_code == 401

    def test_create_portal_token_returns_token(self, client, monkeypatch, seeded_temp_db):
        """Adjuster can create portal token; token works for claimant."""

        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "token")
        reload_settings()

        create_resp = client.post(
            "/api/claims/CLM-TEST001/portal-token",
            json={},
            headers={"X-API-Key": "sk-adj"},
        )
        assert create_resp.status_code == 200
        data = create_resp.json()
        assert data["claim_id"] == "CLM-TEST001"
        assert "token" in data
        token = data["token"]
        assert len(token) > 20

        list_resp = client.get(
            "/api/portal/claims",
            headers=_portal_token_headers(token),
        )
        assert list_resp.status_code == 200
        assert list_resp.json()["claims"][0]["id"] == "CLM-TEST001"

    def test_create_portal_token_404_claim_not_found(self, client, monkeypatch):
        """POST /claims/{id}/portal-token returns 404 when claim does not exist."""
        monkeypatch.setenv("API_KEYS", "sk-adj:adjuster")
        monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
        reload_settings()
        resp = client.post(
            "/api/claims/CLM-NONEXISTENT/portal-token",
            json={},
            headers={"X-API-Key": "sk-adj"},
        )
        assert resp.status_code == 404


# -------------------------------------------------------------------
# Document upload, follow-up response
# -------------------------------------------------------------------


class TestPortalDocumentUpload:
    """Portal document upload and follow-up response."""

    def test_upload_document_success(self, client, monkeypatch):
        """Claimant can upload document with valid policy+vin."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.post(
            "/api/portal/claims/CLM-TEST001/documents",
            files=[("file", ("report.pdf", b"fake pdf content", "application/pdf"))],
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST001"
        assert "document_id" in data
        assert data["document"]["document_type"] in (
            "police_report",
            "estimate",
            "medical_record",
            "photo",
            "pdf",
            "other",
        )

    def test_upload_document_400_wrong_file_type(self, client, monkeypatch):
        """Portal rejects disallowed file types."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.post(
            "/api/portal/claims/CLM-TEST001/documents",
            files=[("file", ("malware.exe", b"fake exe", "application/octet-stream"))],
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 400
        assert "not allowed" in resp.json()["detail"].lower()


class TestPortalAttachmentDownload:
    """Portal attachment download and chain-of-custody audit."""

    def test_portal_attachment_download_appends_document_downloaded_audit(
        self, client, monkeypatch, tmp_path
    ):
        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        import claim_agent.storage.factory as factory_mod

        monkeypatch.setattr(factory_mod, "_storage_instance", None)
        storage = factory_mod.get_storage_adapter()
        stored_key = storage.save(
            claim_id="CLM-TEST001",
            filename="portal_chain.pdf",
            content=b"portal attachment bytes",
        )
        resp = client.get(
            f"/api/portal/claims/CLM-TEST001/attachments/{stored_key}",
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 200
        assert resp.content == b"portal attachment bytes"
        with get_connection() as conn:
            row = conn.execute(
                text(
                    "SELECT action, actor_id, after_state FROM claim_audit_log "
                    "WHERE claim_id = :cid AND action = 'document_downloaded' "
                    "ORDER BY id DESC LIMIT 1"
                ),
                {"cid": "CLM-TEST001"},
            ).fetchone()
        assert row is not None
        state = json.loads(row[2])
        assert state["storage_key"] == stored_key
        assert state["channel"] == "portal"

    def test_portal_attachment_download_fails_when_audit_insert_fails(
        self, monkeypatch, tmp_path
    ):
        from claim_agent.api.server import app
        from claim_agent.db.repository import ClaimRepository

        monkeypatch.setenv("ATTACHMENT_STORAGE_PATH", str(tmp_path / "attachments"))
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        import claim_agent.storage.factory as factory_mod

        monkeypatch.setattr(factory_mod, "_storage_instance", None)
        storage = factory_mod.get_storage_adapter()
        stored_key = storage.save(
            claim_id="CLM-TEST001",
            filename="portal_blocked.pdf",
            content=b"portal secret",
        )

        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("audit insert failed")

        monkeypatch.setattr(ClaimRepository, "insert_audit_entry", fail_audit)
        with TestClient(app, raise_server_exceptions=False) as tc:
            resp = tc.get(
                f"/api/portal/claims/CLM-TEST001/attachments/{stored_key}",
                headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
            )
        assert resp.status_code == 500
        assert b"portal secret" not in resp.content


class TestPortalFollowUpResponse:
    """Portal follow-up response recording."""

    def test_record_follow_up_response_success(
        self, client, monkeypatch, seeded_temp_db
    ):
        """Claimant can record response to an existing follow-up message."""
        from claim_agent.db.repository import ClaimRepository

        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()

        repo = ClaimRepository(db_path=seeded_temp_db)
        msg_id = repo.create_follow_up_message(
            "CLM-TEST001",
            user_type="claimant",
            message_content="Please upload your photos.",
        )
        repo.mark_follow_up_sent(msg_id)

        resp = client.post(
            "/api/portal/claims/CLM-TEST001/follow-up/record-response",
            json={"message_id": msg_id, "response_content": "I uploaded 3 photos."},
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 200
        assert resp.json().get("success") is True


# -------------------------------------------------------------------
# Portal disabled returns 503
# -------------------------------------------------------------------


class TestPortalDisabled:
    """Portal returns 503 when disabled."""

    def test_list_claims_503_when_portal_disabled(self, client, monkeypatch):
        """GET /portal/claims returns 503 when CLAIMANT_PORTAL_ENABLED=false."""
        monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "false")
        reload_settings()
        resp = client.get(
            "/api/portal/claims",
            headers=_portal_policy_vin_headers("POL-001", "1HGBH41JXMN109186"),
        )
        assert resp.status_code == 503
        assert "disabled" in resp.json().get("detail", "").lower()
