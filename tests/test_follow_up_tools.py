"""Tests for follow-up tools."""

import json
import os
import tempfile
from datetime import date

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.models.party import ClaimPartyInput
from claim_agent.tools.follow_up_tools import (
    check_pending_responses,
    record_user_response,
    send_user_message,
)


@pytest.fixture
def temp_db():
    """Temp DB with CLAIMS_DB_PATH set so tools use it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    prev = os.environ.get("CLAIMS_DB_PATH")
    os.environ["CLAIMS_DB_PATH"] = path
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


def test_send_user_message_success(repo, claim_id):
    # Use repair_shop: delivery is attempted (stub) without requiring email/phone.
    # claimant/policyholder need email or phone AND notifications enabled.
    result = send_user_message.run(
        claim_id=claim_id,
        user_type="repair_shop",
        message_content="Please submit the supplement estimate.",
        identifier="SHOP-001",
    )
    data = json.loads(result)
    assert data["success"] is True
    assert "message_id" in data
    assert data["message_id"] > 0


def test_send_user_message_invalid_claim(repo):
    result = send_user_message.run(
        claim_id="CLM-NONEXISTENT",
        user_type="claimant",
        message_content="Please upload photos.",
    )
    data = json.loads(result)
    assert data["success"] is False
    assert "not found" in data["message"].lower()


def test_send_user_message_invalid_user_type(repo, claim_id):
    result = send_user_message.run(
        claim_id=claim_id,
        user_type="invalid_type",
        message_content="Please upload photos.",
    )
    data = json.loads(result)
    assert data["success"] is False
    assert "user_type" in data["message"]


def test_send_user_message_claimant_no_contact_returns_false(repo, claim_id):
    """Claimant/policyholder without email or phone is not delivered; status stays pending."""
    result = send_user_message.run(
        claim_id=claim_id,
        user_type="claimant",
        message_content="Please upload photos.",
    )
    data = json.loads(result)
    assert data["success"] is False
    assert "contact" in data["message"].lower() or "not delivered" in data["message"].lower()


def test_send_user_message_claimant_resolves_contact_from_parties(repo, claim_id, monkeypatch):
    """When claimant has contact in claim_parties, message is delivered without explicit email/phone."""
    monkeypatch.setattr(
        "claim_agent.notifications.user.get_notification_config",
        lambda: {"email_enabled": True, "sms_enabled": True},
    )
    repo.add_claim_party(
        claim_id,
        ClaimPartyInput(
            party_type="claimant",
            name="Jane Doe",
            email="jane@example.com",
            phone="555-123-4567",
        ),
    )
    result = send_user_message.run(
        claim_id=claim_id,
        user_type="claimant",
        message_content="Please upload damage photos.",
    )
    data = json.loads(result)
    assert data["success"] is True
    assert data["message_id"] > 0


def test_record_user_response_rejects_blank_claim_id(repo, claim_id):
    """When claim_id is provided but blank/whitespace, return error."""
    msg_id = repo.create_follow_up_message(
        claim_id, "claimant", "Please upload photos.", actor_id="workflow"
    )
    result = record_user_response.run(
        message_id=msg_id,
        response_content="My response.",
        claim_id="   ",
    )
    data = json.loads(result)
    assert data["success"] is False
    assert "blank" in data["message"].lower() or "whitespace" in data["message"].lower()


def test_record_user_response_success(repo, claim_id):
    msg_id = repo.create_follow_up_message(
        claim_id, "claimant", "Please upload photos.", actor_id="workflow"
    )
    result = record_user_response.run(
        message_id=msg_id,
        response_content="I've uploaded 3 photos to the portal.",
    )
    data = json.loads(result)
    assert data["success"] is True


def test_record_user_response_invalid_message(repo):
    result = record_user_response.run(
        message_id=99999,
        response_content="My response.",
    )
    data = json.loads(result)
    assert data["success"] is False


def test_record_user_response_rejects_cross_claim_when_claim_id_provided(repo, claim_id):
    """When claim_id is provided, tool rejects message from another claim."""
    msg_id = repo.create_follow_up_message(
        claim_id, "claimant", "Please upload photos.", actor_id="workflow"
    )
    other_claim_id = repo.create_claim(
        ClaimInput(
            policy_number="POL-456",
            vin="2HGBH41JXMN109187",
            vehicle_year=2020,
            vehicle_make="Toyota",
            vehicle_model="Camry",
            incident_date=date(2025, 2, 1),
            incident_description="Side swipe",
            damage_description="Door damage",
        )
    )
    result = record_user_response.run(
        message_id=msg_id,
        response_content="My response.",
        claim_id=other_claim_id,
    )
    data = json.loads(result)
    assert data["success"] is False
    assert "does not belong" in data["message"]


def test_check_pending_responses(repo, claim_id):
    repo.create_follow_up_message(
        claim_id, "claimant", "Please upload photos.", actor_id="workflow"
    )
    result = check_pending_responses.run(claim_id=claim_id)
    data = json.loads(result)
    assert data["error"] is None
    assert len(data["pending"]) >= 1
    assert data["pending"][0]["user_type"] == "claimant"


def test_check_pending_responses_invalid_claim(repo):
    result = check_pending_responses.run(claim_id="CLM-NONEXISTENT")
    data = json.loads(result)
    assert data["error"] is not None
    assert "not found" in data["error"].lower()
