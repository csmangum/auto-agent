"""Integration tests for payments API endpoints."""

import pytest

from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput


@pytest.fixture
def claim_for_payments(integration_db: str) -> str:
    """Create a claim and return its ID for payment tests."""
    repo = ClaimRepository(db_path=integration_db)
    claim_id = repo.create_claim(
        ClaimInput(
            policy_number="POL-PAY",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-01-15",
            incident_description="Test claim for payments.",
            damage_description="Rear bumper damage.",
            estimated_damage=2500.0,
        )
    )
    return claim_id


class TestPaymentsAPI:
    """Integration tests for /api/claims/{claim_id}/payments endpoints."""

    @pytest.mark.integration
    def test_create_payment_returns_201(
        self, api_client, claim_for_payments: str
    ):
        """Create payment returns 201 with payment record."""
        resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments",
            json={
                "claim_id": claim_for_payments,
                "amount": 1500.0,
                "payee": "ABC Repair Shop",
                "payee_type": "repair_shop",
                "payment_method": "check",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["claim_id"] == claim_for_payments
        assert data["amount"] == 1500.0
        assert data["payee"] == "ABC Repair Shop"
        assert data["status"] == "authorized"
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.integration
    def test_list_payments_returns_200(
        self, api_client, claim_for_payments: str
    ):
        """List payments returns 200 with paginated results."""
        # Create a payment first
        api_client.post(
            f"/api/claims/{claim_for_payments}/payments",
            json={
                "claim_id": claim_for_payments,
                "amount": 500.0,
                "payee": "Test Payee",
                "payee_type": "claimant",
                "payment_method": "check",
            },
        )
        resp = api_client.get(f"/api/claims/{claim_for_payments}/payments")
        assert resp.status_code == 200
        data = resp.json()
        assert "payments" in data
        assert data["total"] >= 1
        assert data["limit"] == 100
        assert data["offset"] == 0
        assert len(data["payments"]) >= 1

    @pytest.mark.integration
    def test_list_payments_nonexistent_claim_returns_404(self, api_client):
        """List payments for non-existent claim returns 404."""
        resp = api_client.get("/api/claims/CLM-NONEXISTENT/payments")
        assert resp.status_code == 404
        assert "Claim not found" in resp.json().get("detail", "")

    @pytest.mark.integration
    def test_get_payment_returns_200(
        self, api_client, claim_for_payments: str
    ):
        """Get single payment returns 200."""
        create_resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments",
            json={
                "claim_id": claim_for_payments,
                "amount": 750.0,
                "payee": "Single Payee",
                "payee_type": "claimant",
                "payment_method": "ach",
            },
        )
        payment_id = create_resp.json()["id"]
        resp = api_client.get(
            f"/api/claims/{claim_for_payments}/payments/{payment_id}"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == payment_id
        assert data["amount"] == 750.0

    @pytest.mark.integration
    def test_get_payment_nonexistent_returns_404(
        self, api_client, claim_for_payments: str
    ):
        """Get non-existent payment returns 404."""
        resp = api_client.get(
            f"/api/claims/{claim_for_payments}/payments/99999"
        )
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_issue_payment_returns_200(
        self, api_client, claim_for_payments: str
    ):
        """Issue payment transitions authorized -> issued."""
        create_resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments",
            json={
                "claim_id": claim_for_payments,
                "amount": 300.0,
                "payee": "Issue Test",
                "payee_type": "claimant",
                "payment_method": "check",
            },
        )
        payment_id = create_resp.json()["id"]
        resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments/{payment_id}/issue",
            json={"check_number": "CHK-12345"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "issued"
        assert data["check_number"] == "CHK-12345"
        assert data["issued_at"] is not None

    @pytest.mark.integration
    def test_clear_payment_returns_200(
        self, api_client, claim_for_payments: str
    ):
        """Clear payment transitions issued -> cleared."""
        create_resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments",
            json={
                "claim_id": claim_for_payments,
                "amount": 200.0,
                "payee": "Clear Test",
                "payee_type": "claimant",
                "payment_method": "ach",
            },
        )
        payment_id = create_resp.json()["id"]
        api_client.post(
            f"/api/claims/{claim_for_payments}/payments/{payment_id}/issue"
        )
        resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments/{payment_id}/clear"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cleared"
        assert data["cleared_at"] is not None

    @pytest.mark.integration
    def test_void_payment_returns_200(
        self, api_client, claim_for_payments: str
    ):
        """Void payment from authorized status."""
        create_resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments",
            json={
                "claim_id": claim_for_payments,
                "amount": 100.0,
                "payee": "Void Test",
                "payee_type": "claimant",
                "payment_method": "check",
            },
        )
        payment_id = create_resp.json()["id"]
        resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments/{payment_id}/void",
            json={"reason": "Duplicate payment"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "voided"
        assert data["void_reason"] == "Duplicate payment"
        assert data["voided_at"] is not None

    @pytest.mark.integration
    def test_create_payment_claim_id_mismatch_returns_400(
        self, api_client, claim_for_payments: str
    ):
        """Create payment with mismatched claim_id in body returns 400."""
        resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments",
            json={
                "claim_id": "CLM-WRONG",
                "amount": 100.0,
                "payee": "X",
                "payee_type": "claimant",
                "payment_method": "check",
            },
        )
        assert resp.status_code == 400

    @pytest.mark.integration
    def test_create_payment_nonexistent_claim_returns_404(self, api_client):
        """Create payment for non-existent claim returns 404."""
        resp = api_client.post(
            "/api/claims/CLM-NONEXISTENT/payments",
            json={
                "claim_id": "CLM-NONEXISTENT",
                "amount": 100.0,
                "payee": "X",
                "payee_type": "claimant",
                "payment_method": "check",
            },
        )
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_create_payment_authority_exceeded_returns_403(
        self, api_client, claim_for_payments: str, monkeypatch
    ):
        """Create payment exceeding authority limit returns 403."""
        monkeypatch.setenv("PAYMENT_ADJUSTER_LIMIT", "100")
        monkeypatch.setenv("PAYMENT_SUPERVISOR_LIMIT", "100")
        monkeypatch.setenv("PAYMENT_EXECUTIVE_LIMIT", "100")
        # Reset settings so new env is picked up
        import claim_agent.config as _cfg

        _cfg._settings = None
        resp = api_client.post(
            f"/api/claims/{claim_for_payments}/payments",
            json={
                "claim_id": claim_for_payments,
                "amount": 500.0,
                "payee": "Over Limit",
                "payee_type": "claimant",
                "payment_method": "check",
            },
        )
        assert resp.status_code == 403
        assert "exceeds authority" in resp.json().get("detail", "").lower()
