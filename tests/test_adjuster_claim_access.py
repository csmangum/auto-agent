"""Adjuster claim scoping: assignee must match API key identity (Auth Phase 2)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from claim_agent.config import reload_settings
from claim_agent.db.database import get_connection


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    from claim_agent.api.server import app

    return TestClient(app)


def _insert_scoped_claims(db_path: str) -> None:
    """Two claims with distinct assignees (minimal columns)."""
    with get_connection(db_path) as conn:
        for cid, assignee in (
            ("CLM-SCOPE-A", "user-a"),
            ("CLM-SCOPE-B", "user-b"),
        ):
            conn.execute(
                text(
                    """
                    INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
                    vehicle_model, incident_date, incident_description, damage_description,
                    estimated_damage, claim_type, status, payout_amount, assignee)
                    VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                            :incident_date, :incident_description, :damage_description,
                            :estimated_damage, :claim_type, :status, :payout_amount, :assignee)
                    """
                ),
                {
                    "id": cid,
                    "policy_number": "POL-X",
                    "vin": "1HGBH41JXMN109186",
                    "vehicle_year": 2021,
                    "vehicle_make": "Honda",
                    "vehicle_model": "Accord",
                    "incident_date": "2025-01-15",
                    "incident_description": "Test",
                    "damage_description": "Dent",
                    "estimated_damage": 1000.0,
                    "claim_type": "new",
                    "status": "open",
                    "payout_amount": 1000.0,
                    "assignee": assignee,
                },
            )


def test_adjuster_can_read_own_claim(temp_db, monkeypatch, client):
    monkeypatch.setenv("API_KEYS", "k1:adjuster:user-a")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()
    _insert_scoped_claims(temp_db)

    r = client.get("/api/v1/claims/CLM-SCOPE-A", headers={"X-API-Key": "k1"})
    assert r.status_code == 200
    assert r.json()["id"] == "CLM-SCOPE-A"


def test_adjuster_get_other_assignee_claim_404(temp_db, monkeypatch, client):
    monkeypatch.setenv("API_KEYS", "k1:adjuster:user-a")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()
    _insert_scoped_claims(temp_db)

    r = client.get("/api/v1/claims/CLM-SCOPE-B", headers={"X-API-Key": "k1"})
    assert r.status_code == 404


def test_adjuster_patch_reserve_other_assignee_404(temp_db, monkeypatch, client):
    monkeypatch.setenv("API_KEYS", "k1:adjuster:user-a")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()
    _insert_scoped_claims(temp_db)

    r = client.patch(
        "/api/v1/claims/CLM-SCOPE-B/reserve",
        headers={"X-API-Key": "k1"},
        json={"reserve_amount": 5000.0, "reason": "test"},
    )
    assert r.status_code == 404


def test_review_queue_adjuster_cannot_target_other_assignee_param(temp_db, monkeypatch, client):
    """Adjuster identity is forced; ?assignee= does not widen scope to another adjuster."""
    with get_connection(temp_db) as conn:
        conn.execute(
            text(
                """
                INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
                vehicle_model, incident_date, incident_description, damage_description,
                estimated_damage, claim_type, status, payout_amount, assignee, priority, due_at)
                VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                        :incident_date, :incident_description, :damage_description,
                        :estimated_damage, :claim_type, :status, :payout_amount, :assignee,
                        :priority, :due_at)
                """
            ),
            {
                "id": "CLM-RQ-B",
                "policy_number": "POL-RQ",
                "vin": "1HGBH41JXMN109187",
                "vehicle_year": 2021,
                "vehicle_make": "Honda",
                "vehicle_model": "Accord",
                "incident_date": "2025-01-15",
                "incident_description": "Test",
                "damage_description": "Dent",
                "estimated_damage": 1000.0,
                "claim_type": "new",
                "status": "needs_review",
                "payout_amount": 1000.0,
                "assignee": "user-b",
                "priority": "high",
                "due_at": "2025-12-31T00:00:00Z",
            },
        )

    monkeypatch.setenv("API_KEYS", "k1:adjuster:user-a")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()

    r = client.get(
        "/api/v1/claims/review-queue?assignee=user-b",
        headers={"X-API-Key": "k1"},
    )
    assert r.status_code == 200
    data = r.json()
    ids = [c["id"] for c in data.get("claims", [])]
    assert "CLM-RQ-B" not in ids


def test_supervisor_still_sees_other_assignee_claim(temp_db, monkeypatch, client):
    monkeypatch.setenv("API_KEYS", "ks:supervisor")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.delenv("CLAIMS_API_KEY", raising=False)
    reload_settings()
    _insert_scoped_claims(temp_db)

    r = client.get("/api/v1/claims/CLM-SCOPE-B", headers={"X-API-Key": "ks"})
    assert r.status_code == 200
