"""Tests for the portal rental-summary endpoint.

GET /api/portal/claims/{id}/rental-summary
"""

import pytest
from fastapi.testclient import TestClient

from claim_agent.config import reload_settings
from claim_agent.db.rental_repository import RentalAuthorizationRepository


@pytest.fixture(autouse=True)
def _use_seeded_db(seeded_temp_db):
    """Use seeded temp DB for all portal rental API tests."""
    yield


@pytest.fixture(autouse=True)
def _enable_portal(monkeypatch):
    """Enable the claimant portal for all portal rental API tests."""
    monkeypatch.setenv("CLAIMANT_PORTAL_ENABLED", "true")
    reload_settings()
    yield


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Clear rate limit buckets before each test."""
    from claim_agent.api.rate_limit import clear_rate_limit_buckets

    clear_rate_limit_buckets()
    yield


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    from claim_agent.api.server import app

    return TestClient(app)


def _policy_vin_headers(policy_number: str, vin: str) -> dict:
    return {"X-Policy-Number": policy_number, "X-Vin": vin}


# Headers for CLM-TEST001 (POL-001 / Honda Accord VIN)
_CLM001_HEADERS = _policy_vin_headers("POL-001", "1HGBH41JXMN109186")


class TestRentalSummaryEndpoint:
    """Tests for GET /api/portal/claims/{id}/rental-summary."""

    def test_returns_200_with_null_rental_when_no_authorization(
        self, client, monkeypatch
    ):
        """When no rental authorization exists, returns 200 with rental=null."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.get(
            "/api/portal/claims/CLM-TEST001/rental-summary",
            headers=_CLM001_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST001"
        assert data["rental"] is None

    def test_returns_404_for_unknown_claim(self, client, monkeypatch):
        """Returns 404 when claim_id does not exist."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.get(
            "/api/portal/claims/CLM-DOES-NOT-EXIST/rental-summary",
            headers=_CLM001_HEADERS,
        )
        assert resp.status_code == 404

    def test_returns_404_when_claim_not_in_session(self, client, monkeypatch):
        """Returns 404 when claimant does not have access to the requested claim."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        # CLM-TEST002 belongs to POL-002; POL-001 cannot access it
        resp = client.get(
            "/api/portal/claims/CLM-TEST002/rental-summary",
            headers=_CLM001_HEADERS,
        )
        assert resp.status_code == 404

    def test_returns_rental_summary_when_authorization_exists(
        self, client, monkeypatch, seeded_temp_db
    ):
        """Returns sanitized rental summary after an authorization is persisted."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()

        # Persist a rental authorization directly via the repository
        repo = RentalAuthorizationRepository(db_path=seeded_temp_db)
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=7,
            daily_cap=35.0,
            reservation_ref="RES-INTERNAL",
            agency_ref="AGY-INTERNAL",
            direct_bill=False,
            status="authorized",
            reimbursement_id="RENT-PORTAL01",
            amount_approved=245.0,
        )

        resp = client.get(
            "/api/portal/claims/CLM-TEST001/rental-summary",
            headers=_CLM001_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["claim_id"] == "CLM-TEST001"
        rental = data["rental"]
        assert rental is not None

        # Safe fields present
        assert rental["authorized_days"] == 7
        assert rental["daily_cap"] == 35.0
        assert rental["direct_bill"] is False
        assert rental["status"] == "authorized"
        assert rental["reimbursement_id"] == "RENT-PORTAL01"
        assert rental["amount_approved"] == 245.0
        assert "created_at" in rental
        assert "updated_at" in rental

        # Vendor-sensitive fields must NOT be present
        assert "reservation_ref" not in rental
        assert "agency_ref" not in rental
        assert "id" not in rental

    def test_direct_bill_true_returned_correctly(
        self, client, monkeypatch, seeded_temp_db
    ):
        """direct_bill=True is returned as boolean true in the portal summary."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()

        repo = RentalAuthorizationRepository(db_path=seeded_temp_db)
        repo.upsert_authorization(
            claim_id="CLM-TEST001",
            authorized_days=5,
            daily_cap=40.0,
            direct_bill=True,
            status="authorized",
            reimbursement_id="RENT-DIRECT01",
            amount_approved=200.0,
        )

        resp = client.get(
            "/api/portal/claims/CLM-TEST001/rental-summary",
            headers=_CLM001_HEADERS,
        )
        assert resp.status_code == 200
        assert resp.json()["rental"]["direct_bill"] is True

    def test_requires_auth(self, client, monkeypatch):
        """Returns 401 when no authentication headers are provided."""
        monkeypatch.setenv("CLAIMANT_VERIFICATION_MODE", "policy_vin")
        reload_settings()
        resp = client.get("/api/portal/claims/CLM-TEST001/rental-summary")
        assert resp.status_code == 401
