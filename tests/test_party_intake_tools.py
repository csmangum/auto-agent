"""Tests for witness/attorney party intake tools (issue #267)."""

import json
import os
import tempfile
from datetime import date

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput
from claim_agent.tools.party_intake_tools import (
    record_attorney_representation,
    record_witness_party,
    record_witness_statement,
    update_witness_party,
)


@pytest.fixture
def temp_db():
    from claim_agent.config import reload_settings

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    prev = os.environ.get("CLAIMS_DB_PATH")
    os.environ["CLAIMS_DB_PATH"] = path
    reload_settings()
    try:
        yield path
    finally:
        if prev is None:
            os.environ.pop("CLAIMS_DB_PATH", None)
        else:
            os.environ["CLAIMS_DB_PATH"] = prev
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture
def repo(temp_db):
    return ClaimRepository(db_path=temp_db)


@pytest.fixture
def claim_id(repo):
    return repo.create_claim(
        ClaimInput(
            policy_number="POL-123",
            vin="1VIN",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Collision",
            damage_description="Front",
            parties=[
                ClaimPartyInput(
                    party_type="claimant",
                    name="C",
                    email="c@example.com",
                ),
            ],
        )
    )


def test_record_witness_party_and_statement(repo, claim_id):
    r = json.loads(
        record_witness_party.run(
            claim_id=claim_id,
            name="Alex Witness",
            role="eyewitness",
            email="alex@w.com",
            phone="555-0100",
        )
    )
    assert r["success"] is True
    wid = r["party_id"]
    r2 = json.loads(
        record_witness_statement.run(
            claim_id=claim_id,
            witness_party_id=wid,
            statement_text="I saw the red car run the light.",
        )
    )
    assert r2["success"] is True
    notes = repo.get_notes(claim_id)
    assert any("witness_statement" in (n.get("note") or "") for n in notes)


def test_update_witness_party(repo, claim_id):
    r = json.loads(
        record_witness_party.run(claim_id=claim_id, name="Pat", role="passenger")
    )
    wid = r["party_id"]
    r2 = json.loads(
        update_witness_party.run(
            claim_id=claim_id,
            party_id=wid,
            phone="555-9999",
            role="passenger / witness",
        )
    )
    assert r2["success"] is True
    parties = repo.get_claim_parties(claim_id, party_type="witness")
    assert parties[0]["phone"] == "555-9999"


def test_record_attorney_representation(repo, claim_id):
    r = json.loads(
        record_attorney_representation.run(
            claim_id=claim_id,
            attorney_name="Law Firm LLP",
            email="law@firm.com",
            phone="555-0200",
        )
    )
    assert r["success"] is True
    assert "attorney_party_id" in r
    contact = repo.get_primary_contact_for_user_type(claim_id, "claimant")
    assert contact is not None
    assert contact["party_type"] == "attorney"
    assert contact["email"] == "law@firm.com"


def test_record_attorney_idempotent_when_already_represented(repo, claim_id):
    first = json.loads(
        record_attorney_representation.run(
            claim_id=claim_id,
            attorney_name="First Firm",
            email="a1@firm.com",
        )
    )
    assert first["success"] is True
    second = json.loads(
        record_attorney_representation.run(
            claim_id=claim_id,
            attorney_name="Second Firm",
            email="a2@firm.com",
        )
    )
    assert second["success"] is True
    assert "already" in (second.get("message") or "").lower()
    attorneys = repo.get_claim_parties(claim_id, party_type="attorney")
    assert len(attorneys) == 1
