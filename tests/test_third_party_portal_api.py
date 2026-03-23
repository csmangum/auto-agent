"""Tests for third-party portal routes (/api/third-party-portal/*) and token minting."""

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
def third_party_portal_on(monkeypatch):
    monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
    reload_settings()
    yield
    monkeypatch.delenv("THIRD_PARTY_PORTAL_ENABLED", raising=False)
    reload_settings()


@pytest.mark.usefixtures("third_party_portal_on")
class TestThirdPartyPortal:
    def test_mint_token_disabled_returns_503(self, client, monkeypatch):
        monkeypatch.delenv("THIRD_PARTY_PORTAL_ENABLED", raising=False)
        reload_settings()
        resp = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        assert resp.status_code == 503
        monkeypatch.setenv("THIRD_PARTY_PORTAL_ENABLED", "true")
        reload_settings()

    def test_mint_token_success(self, client):
        resp = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST005"
        assert "token" in data
        assert len(data["token"]) > 20

    def test_mint_token_rejects_claimant_party(self, client, seeded_temp_db):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.party import ClaimPartyInput

        repo = ClaimRepository(db_path=seeded_temp_db)
        bad_id = repo.add_claim_party(
            "CLM-TEST005",
            ClaimPartyInput(
                party_type="claimant",
                name="Seed Claimant",
                email="c@example.com",
            ),
        )
        resp = client.post(
            "/api/claims/CLM-TEST005/third-party-portal-token",
            json={"party_id": bad_id},
        )
        assert resp.status_code == 400
        assert "witness" in resp.json()["detail"].lower() or "party" in resp.json()["detail"].lower()

    def test_mint_token_accepts_witness_party(self, client, seeded_temp_db):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.party import ClaimPartyInput

        repo = ClaimRepository(db_path=seeded_temp_db)
        wid = repo.add_claim_party(
            "CLM-TEST005",
            ClaimPartyInput(
                party_type="witness",
                name="Other Driver",
                email="w@example.com",
            ),
        )
        resp = client.post(
            "/api/claims/CLM-TEST005/third-party-portal-token",
            json={"party_id": wid},
        )
        assert resp.status_code == 200
        assert resp.json()["claim_id"] == "CLM-TEST005"

    def test_portal_get_claim_without_token_401(self, client):
        resp = client.get("/api/third-party-portal/claims/CLM-TEST005")
        assert resp.status_code == 401

    def test_portal_get_claim_invalid_token_401(self, client):
        resp = client.get(
            "/api/third-party-portal/claims/CLM-TEST005",
            headers={"X-Third-Party-Access-Token": "not-a-valid-token"},
        )
        assert resp.status_code == 401

    def test_portal_get_claim_excludes_policy_and_vin(self, client):
        mint = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        token = mint.json()["token"]
        resp = client.get(
            "/api/third-party-portal/claims/CLM-TEST005",
            headers={"X-Third-Party-Access-Token": token},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == "CLM-TEST005"
        assert "policy_number" not in body
        assert "vin" not in body
        assert "follow_up_messages" in body
        assert body["parties"] == []

    def test_portal_get_claim_follow_ups_only_other(self, client):
        from claim_agent.db.repository import ClaimRepository

        repo = ClaimRepository()
        repo.create_follow_up_message(
            "CLM-TEST005",
            user_type="claimant",
            message_content="Claimant thread",
            actor_id="workflow",
        )
        other_msg_id = repo.create_follow_up_message(
            "CLM-TEST005",
            user_type="other",
            message_content="Carrier to third party",
            actor_id="workflow",
        )
        mint = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        token = mint.json()["token"]
        resp = client.get(
            "/api/third-party-portal/claims/CLM-TEST005",
            headers={"X-Third-Party-Access-Token": token},
        )
        assert resp.status_code == 200
        msgs = resp.json()["follow_up_messages"]
        assert all((m.get("user_type") or "") == "other" for m in msgs)
        ids = {m["id"] for m in msgs}
        assert other_msg_id in ids

    def test_portal_claim_history_redaction(self, client):
        mint = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        token = mint.json()["token"]
        h = {"X-Third-Party-Access-Token": token}
        resp = client.get("/api/third-party-portal/claims/CLM-TEST005/history", headers=h)
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST005"
        for row in data["history"]:
            assert "details" not in row
            assert "actor_id" not in row

    def test_portal_disabled_returns_503(self, client, monkeypatch):
        mint = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        token = mint.json()["token"]
        monkeypatch.delenv("THIRD_PARTY_PORTAL_ENABLED", raising=False)
        reload_settings()
        resp = client.get(
            "/api/third-party-portal/claims/CLM-TEST005",
            headers={"X-Third-Party-Access-Token": token},
        )
        assert resp.status_code == 503

    def test_portal_record_follow_up_response_success(self, client):
        from claim_agent.db.repository import ClaimRepository

        repo = ClaimRepository()
        msg_id = repo.create_follow_up_message(
            "CLM-TEST005",
            user_type="other",
            message_content="Please provide your statement.",
            actor_id="workflow",
        )
        repo.mark_follow_up_sent(msg_id)
        mint = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        tok = mint.json()["token"]
        h = {"X-Third-Party-Access-Token": tok}
        resp = client.post(
            "/api/third-party-portal/claims/CLM-TEST005/follow-up/record-response",
            headers=h,
            json={"message_id": msg_id, "response_content": "Statement attached."},
        )
        assert resp.status_code == 200
        assert resp.json().get("success") is True

    def test_portal_record_follow_up_rejects_non_other_message(self, client):
        from claim_agent.db.repository import ClaimRepository

        repo = ClaimRepository()
        msg_id = repo.create_follow_up_message(
            "CLM-TEST005",
            user_type="claimant",
            message_content="Claimant-only message.",
            actor_id="workflow",
        )
        repo.mark_follow_up_sent(msg_id)
        mint = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        tok = mint.json()["token"]
        h = {"X-Third-Party-Access-Token": tok}
        resp = client.post(
            "/api/third-party-portal/claims/CLM-TEST005/follow-up/record-response",
            headers=h,
            json={"message_id": msg_id, "response_content": "Trying to reply as third party."},
        )
        assert resp.status_code == 400
        assert "third-party" in resp.json()["detail"].lower()

    def test_portal_dispute_rejects_ineligible_status(self, client):
        mint = client.post("/api/claims/CLM-TEST005/third-party-portal-token", json={})
        tok = mint.json()["token"]
        h = {"X-Third-Party-Access-Token": tok}
        resp = client.post(
            "/api/third-party-portal/claims/CLM-TEST005/dispute",
            headers=h,
            json={
                "dispute_type": "liability_determination",
                "dispute_description": "Test dispute",
                "policyholder_evidence": None,
            },
        )
        assert resp.status_code == 409
        assert "cannot be disputed" in resp.json()["detail"].lower()
