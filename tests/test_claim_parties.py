"""Tests for claim parties (repository CRUD, get_primary_contact_for_user_type)."""

import os
import tempfile
from datetime import date

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import DomainValidationError
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput, PartyRelationshipType


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
    assert parties[0].get("relationships") == []


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
    repo.add_claim_party_relationship(
        claim_id,
        claimant_id,
        attorney_id,
        PartyRelationshipType.REPRESENTED_BY.value,
    )
    claimant_row = repo.get_claim_party_by_type(claim_id, "claimant")
    assert claimant_row is not None
    rels = claimant_row.get("relationships") or []
    assert len(rels) == 1
    assert rels[0]["to_party_id"] == attorney_id
    assert rels[0]["relationship_type"] == PartyRelationshipType.REPRESENTED_BY.value
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


def test_add_claim_party_relationship_missing_party(repo, claim_id):
    c = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="A", email="a@x.com"),
    )
    with pytest.raises(DomainValidationError, match="do not exist"):
        repo.add_claim_party_relationship(
            claim_id, c, 999_999, PartyRelationshipType.REPRESENTED_BY.value
        )


def test_add_claim_party_relationship_invalid_type(repo, claim_id):
    cid = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="A", email="a@x.com"),
    )
    tid = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="attorney", name="B", email="b@x.com"),
    )
    with pytest.raises(DomainValidationError, match="Invalid relationship_type"):
        repo.add_claim_party_relationship(claim_id, cid, tid, "not_a_real_type")


def test_add_claim_party_relationship_self_loop(repo, claim_id):
    cid = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="A", email="a@x.com"),
    )
    with pytest.raises(DomainValidationError, match="must differ"):
        repo.add_claim_party_relationship(
            claim_id, cid, cid, PartyRelationshipType.REPRESENTED_BY.value
        )


def test_add_claim_party_relationship_wrong_claim_id(repo, claim_id):
    other = ClaimInput(
        policy_number="POL-OTHER",
        vin="5YJSA1E26HF123456",
        vehicle_year=2022,
        vehicle_make="Tesla",
        vehicle_model="Model 3",
        incident_date=date(2025, 2, 1),
        incident_description="Other",
        damage_description="Scratch",
    )
    other_id = repo.create_claim(other)
    a = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="A", email="a@x.com"),
    )
    b = repo.add_claim_party(
        other_id,
        ClaimPartyInput(party_type="attorney", name="B", email="b@x.com"),
    )
    with pytest.raises(DomainValidationError, match="same claim"):
        repo.add_claim_party_relationship(
            claim_id, a, b, PartyRelationshipType.REPRESENTED_BY.value
        )


def test_add_claim_party_relationship_duplicate_raises(repo, claim_id):
    c = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="C", email="c@x.com"),
    )
    t = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="attorney", name="T", email="t@x.com"),
    )
    repo.add_claim_party_relationship(
        claim_id, c, t, PartyRelationshipType.WITNESS_FOR.value
    )
    with pytest.raises(DomainValidationError, match="Duplicate party relationship"):
        repo.add_claim_party_relationship(
            claim_id, c, t, PartyRelationshipType.WITNESS_FOR.value
        )


def test_delete_claim_party_relationship(repo, claim_id):
    c = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="claimant", name="C", email="c@x.com"),
    )
    t = repo.add_claim_party(
        claim_id,
        ClaimPartyInput(party_type="attorney", name="T", email="t@x.com"),
    )
    rid = repo.add_claim_party_relationship(
        claim_id, c, t, PartyRelationshipType.REPRESENTED_BY.value
    )
    assert repo.delete_claim_party_relationship(claim_id, rid) is True
    assert repo.delete_claim_party_relationship(claim_id, rid) is False
    parties = repo.get_claim_parties(claim_id)
    claimant = next(p for p in parties if p["id"] == c)
    assert claimant.get("relationships") == []
