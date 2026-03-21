"""FNOL policyholder merge from policy named_insured (issue #266)."""

import os
import tempfile
from datetime import date

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput
from claim_agent.services.fnol_policyholder import (
    merge_fnol_parties_with_named_insured_policyholder,
    policyholder_party_from_named_insured,
)


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


def test_policyholder_from_named_insured_first_with_name():
    ph = policyholder_party_from_named_insured(
        {
            "named_insured": [
                {"name": "John Doe", "email": "j@example.com", "phone": "555-1"},
                {"name": "Jane Doe"},
            ]
        }
    )
    assert ph is not None
    assert ph.party_type == "policyholder"
    assert ph.name == "John Doe"
    assert ph.email == "j@example.com"
    assert ph.phone == "555-1"


def test_policyholder_from_named_insured_full_name():
    ph = policyholder_party_from_named_insured(
        {"named_insured": [{"full_name": "Alex Alternate", "email": "a@x.com"}]}
    )
    assert ph is not None
    assert ph.name == "Alex Alternate"


def test_merge_skips_when_policyholder_present():
    existing = [
        ClaimPartyInput(party_type="claimant", name="C"),
        ClaimPartyInput(party_type="policyholder", name="Already"),
    ]
    out = merge_fnol_parties_with_named_insured_policyholder(
        existing, {"named_insured": [{"name": "From Policy"}]}
    )
    assert len(out) == 2
    assert out[1].name == "Already"


def test_merge_prepends_policyholder_from_policy():
    c = ClaimPartyInput(party_type="claimant", name="Alice")
    out = merge_fnol_parties_with_named_insured_policyholder(
        [c],
        {"named_insured": [{"name": "Bob Holder", "phone": "555-9"}]},
    )
    assert len(out) == 2
    assert out[0].party_type == "policyholder"
    assert out[0].name == "Bob Holder"
    assert out[0].phone == "555-9"
    assert out[1].name == "Alice"


def test_create_claim_auto_policyholder_from_mock_policy(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    claim_id = repo.create_claim(
        ClaimInput(
            policy_number="POL-001",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Test",
            damage_description="Test",
        )
    )
    parties = repo.get_claim_parties(claim_id)
    ph = [p for p in parties if p["party_type"] == "policyholder"]
    assert len(ph) == 1
    assert ph[0]["name"] == "John Doe"
    assert ph[0]["email"] == "john.doe@example.com"


def test_create_claim_no_duplicate_policyholder_when_intake_has_one(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    claim_id = repo.create_claim(
        ClaimInput(
            policy_number="POL-001",
            vin="1HGBH41JXMN109186",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Test",
            damage_description="Test",
            parties=[
                ClaimPartyInput(
                    party_type="policyholder",
                    name="Custom PH",
                    email="custom@example.com",
                ),
            ],
        )
    )
    parties = repo.get_claim_parties(claim_id)
    ph = [p for p in parties if p["party_type"] == "policyholder"]
    assert len(ph) == 1
    assert ph[0]["name"] == "Custom PH"
