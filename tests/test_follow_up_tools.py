"""Tests for follow-up tools."""

import json
import os
import tempfile

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
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
    from claim_agent.models.claim import ClaimInput
    from datetime import date
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
    result = send_user_message.run(
        claim_id=claim_id,
        user_type="claimant",
        message_content="Please upload photos of the damage.",
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
