"""E2E: party relationship REST API (no workflow/LLM)."""

from datetime import date

import pytest

from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput, PartyRelationshipType


@pytest.mark.e2e
def test_e2e_create_and_delete_party_relationship(e2e_client, integration_db: str):
    repo = ClaimRepository(db_path=integration_db)
    claim_id = repo.create_claim(
        ClaimInput(
            policy_number="POL-E2E-REL",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="E2E rel test",
            damage_description="Scratch",
            estimated_damage=500.0,
            parties=[
                ClaimPartyInput(
                    party_type="claimant",
                    name="Pat",
                    email="pat@example.com",
                ),
                ClaimPartyInput(
                    party_type="attorney",
                    name="Atty",
                    email="atty@example.com",
                ),
            ],
        )
    )
    parties = repo.get_claim_parties(claim_id)
    ids = {p["party_type"]: p["id"] for p in parties}
    resp = e2e_client.post(
        f"/api/claims/{claim_id}/party-relationships",
        json={
            "from_party_id": ids["claimant"],
            "to_party_id": ids["attorney"],
            "relationship_type": PartyRelationshipType.REPRESENTED_BY.value,
        },
    )
    assert resp.status_code == 201
    rel_id = resp.json()["id"]
    assert e2e_client.delete(
        f"/api/claims/{claim_id}/party-relationships/{rel_id}"
    ).status_code == 204
