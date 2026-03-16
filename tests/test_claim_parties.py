"""Tests for claim parties (repository CRUD, get_primary_contact_for_user_type)."""

import os
import tempfile

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput
from datetime import date


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture
def repo(temp_db):
    return ClaimRepository(db_path=temp_db)


@pytest.fixture
def claim_id(repo):
    inp = ClaimInput(
        policy_number="POL-123",
        vin="1HGBH41JXMN109186",
        vehicle_year=2021,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date=date(2025, 1, 15),
        incident_description="Rear-end collision",
        damage_description="Bumper damage",
    )
    return repo.create_claim(inp)


def test_add_claim_party(repo, claim_id):
    party = ClaimPartyInput(
        party_type="claimant",
        name="Jane Doe",
        email="jane@example.com",
        phone="555-123-4567",
        role="driver",
    )
    pid = repo.add_claim_party(claim_id, party)
    assert pid > 0
    parties = repo.get_claim_parties(claim_id)
    assert len(parties) == 1
    assert parties[0]["party_type"] == "claimant"
    assert parties[0]["name"] == "Jane Doe"
    assert parties[0]["email"] == "jane@example.com"
    assert parties[0]["phone"] == "555-123-4567"


def test_get_claim_parties_filtered_by_type(repo, claim_id):
    repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="Jane", email="j@x.com"),
    )
    repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="policyholder", name="John", email="j2@x.com"),
    )
    claimants = repo.get_claim_parties(claim_id, party_type="claimant")
    assert len(claimants) == 1
    assert claimants[0]["party_type"] == "claimant"
    policyholders = repo.get_claim_parties(claim_id, party_type="policyholder")
    assert len(policyholders) == 1
    assert policyholders[0]["party_type"] == "policyholder"


def test_get_claim_party_by_type(repo, claim_id):
    repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="Jane", email="j@x.com"),
    )
    p = repo.get_claim_party_by_type(claim_id, "claimant")
    assert p is not None
    assert p["name"] == "Jane"
    assert repo.get_claim_party_by_type(claim_id, "policyholder") is None


def test_update_claim_party(repo, claim_id):
    pid = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="Jane", email="j@x.com"),
    )
    repo.update_claim_party(pid, {"email": "jane.new@example.com"})
    p = repo.get_claim_party_by_type(claim_id, "claimant")
    assert p["email"] == "jane.new@example.com"
    assert p["name"] == "Jane"


def test_get_primary_contact_for_user_type_claimant(repo, claim_id):
    repo.add_claim_party(
        claim_id,
        ClaimPartyInput(
            party_type="claimant",
            name="Jane",
            email="j@x.com",
            phone="555-111",
        ),
    )
    contact = repo.get_primary_contact_for_user_type(claim_id, "claimant")
    assert contact is not None
    assert contact["email"] == "j@x.com"
    assert contact["phone"] == "555-111"


def test_get_primary_contact_for_user_type_claimant_with_attorney(repo, claim_id):
    """When claimant has attorney, return attorney as primary contact."""
    claimant_id = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(
            party_type="claimant",
            name="Jane",
            email="j@x.com",
        ),
    )
    attorney_id = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(
            party_type="attorney",
            name="Law Firm LLC",
            email="attorney@law.com",
            phone="555-999",
        ),
    )
    repo.update_claim_party(claimant_id, {"represented_by_id": attorney_id})
    contact = repo.get_primary_contact_for_user_type(claim_id, "claimant")
    assert contact is not None
    assert contact["email"] == "attorney@law.com"
    assert contact["party_type"] == "attorney"


def test_get_primary_contact_for_user_type_policyholder(repo, claim_id):
    repo.add_claim_party(
        claim_id,
        ClaimPartyInput(
            party_type="policyholder",
            name="John",
            phone="555-222",
        ),
    )
    contact = repo.get_primary_contact_for_user_type(claim_id, "policyholder")
    assert contact is not None
    assert contact["phone"] == "555-222"


def test_get_primary_contact_for_user_type_repair_shop_returns_none(repo, claim_id):
    """repair_shop has no party record; returns None."""
    contact = repo.get_primary_contact_for_user_type(claim_id, "repair_shop")
    assert contact is None


def test_create_claim_with_parties(repo):
    inp = ClaimInput(
        policy_number="POL-456",
        vin="5YJSA1E26HF123456",
        vehicle_year=2022,
        vehicle_make="Tesla",
        vehicle_model="Model 3",
        incident_date=date(2025, 2, 1),
        incident_description="Parking lot scrape",
        damage_description="Bumper scratch",
        parties=[
            ClaimPartyInput(
                party_type="claimant",
                name="Alice",
                email="alice@example.com",
            ),
            ClaimPartyInput(
                party_type="policyholder",
                name="Bob",
                phone="555-333",
            ),
        ],
    )
    claim_id = repo.create_claim(inp)
    parties = repo.get_claim_parties(claim_id)
    assert len(parties) == 2
    types = {p["party_type"] for p in parties}
    assert types == {"claimant", "policyholder"}
