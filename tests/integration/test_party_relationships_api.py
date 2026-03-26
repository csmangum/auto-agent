"""Integration tests for claim party relationship API endpoints."""

from datetime import date

import pytest

from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput, PartyRelationshipType


@pytest.fixture
def claim_with_two_parties(integration_db: str) -> tuple[str, int, int]:
    """Claim with claimant and attorney; returns (claim_id, claimant_id, attorney_id)."""
    repo = ClaimRepository(db_path=integration_db)
    claim_id = repo.create_claim(
        ClaimInput(
            policy_number="POL-REL",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Test",
            damage_description="Dent",
            estimated_damage=1000.0,
            parties=[
                ClaimPartyInput(
                    party_type="claimant",
                    name="Jane",
                    email="jane@example.com",
                ),
                ClaimPartyInput(
                    party_type="attorney",
                    name="Law Co",
                    email="law@example.com",
                ),
            ],
        )
    )
    parties = repo.get_claim_parties(claim_id)
    by_type = {p["party_type"]: int(p["id"]) for p in parties}
    return claim_id, by_type["claimant"], by_type["attorney"]


class TestPartyRelationshipsAPI:
    """Tests for POST/DELETE /api/claims/{claim_id}/party-relationships."""

    @pytest.mark.integration
    def test_create_and_delete_party_relationship(
        self, api_client, claim_with_two_parties: tuple[str, int, int]
    ):
        claim_id, claimant_id, attorney_id = claim_with_two_parties
        create = api_client.post(
            f"/api/v1/claims/{claim_id}/party-relationships",
            json={
                "from_party_id": claimant_id,
                "to_party_id": attorney_id,
                "relationship_type": PartyRelationshipType.REPRESENTED_BY.value,
            },
        )
        assert create.status_code == 201
        body = create.json()
        assert body["claim_id"] == claim_id
        assert body["from_party_id"] == claimant_id
        assert body["to_party_id"] == attorney_id
        assert body["relationship_type"] == PartyRelationshipType.REPRESENTED_BY.value
        rel_id = body["id"]

        detail = api_client.get(f"/api/v1/claims/{claim_id}")
        assert detail.status_code == 200
        parties = detail.json()["parties"]
        claimant = next(p for p in parties if p["id"] == claimant_id)
        assert "represented_by_id" not in claimant
        rels = claimant.get("relationships") or []
        assert len(rels) == 1
        assert rels[0]["to_party_id"] == attorney_id

        delete = api_client.delete(
            f"/api/v1/claims/{claim_id}/party-relationships/{rel_id}",
        )
        assert delete.status_code == 204

        detail2 = api_client.get(f"/api/v1/claims/{claim_id}")
        claimant2 = next(p for p in detail2.json()["parties"] if p["id"] == claimant_id)
        assert (claimant2.get("relationships") or []) == []

    @pytest.mark.integration
    def test_create_duplicate_returns_400(
        self, api_client, claim_with_two_parties: tuple[str, int, int]
    ):
        claim_id, claimant_id, attorney_id = claim_with_two_parties
        payload = {
            "from_party_id": claimant_id,
            "to_party_id": attorney_id,
            "relationship_type": PartyRelationshipType.LIENHOLDER_FOR.value,
        }
        assert api_client.post(
            f"/api/v1/claims/{claim_id}/party-relationships", json=payload
        ).status_code == 201
        dup = api_client.post(
            f"/api/v1/claims/{claim_id}/party-relationships", json=payload
        )
        assert dup.status_code == 400
        assert "Duplicate" in dup.json()["detail"]

    @pytest.mark.integration
    def test_delete_unknown_relationship_returns_404(
        self, api_client, claim_with_two_parties: tuple[str, int, int]
    ):
        claim_id, _, _ = claim_with_two_parties
        resp = api_client.delete(f"/api/v1/claims/{claim_id}/party-relationships/999999")
        assert resp.status_code == 404

    @pytest.mark.integration
    def test_create_on_missing_claim_returns_404(self, api_client):
        resp = api_client.post(
            "/api/v1/claims/CLM-NONEXIST/party-relationships",
            json={
                "from_party_id": 1,
                "to_party_id": 2,
                "relationship_type": PartyRelationshipType.REPRESENTED_BY.value,
            },
        )
        assert resp.status_code == 404
