"""Tests for AdjusterActionService."""

import os
import tempfile

import pytest

from claim_agent.db.constants import STATUS_NEEDS_REVIEW
from claim_agent.db.database import get_connection, init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.claim import ClaimInput
from claim_agent.services.adjuster_action_service import AdjusterActionService


@pytest.fixture
def temp_db():
    """Create a temporary SQLite database path and init schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
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
def service(repo):
    return AdjusterActionService(repo=repo)


def test_assign_delegates_to_repo(service, repo):
    """Assign delegates to repo.assign_claim."""
    claim_input = ClaimInput(
        policy_number="POL-A",
        vin="VIN-A",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-15",
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = repo.create_claim(claim_input)
    with get_connection(repo._db_path) as conn:
        conn.execute(
            "UPDATE claims SET status = ? WHERE id = ?",
            (STATUS_NEEDS_REVIEW, claim_id),
        )

    service.assign(claim_id, "adjuster-1", actor_id="workflow")
    claim = repo.get_claim(claim_id)
    assert claim["assignee"] == "adjuster-1"


def test_assign_raises_on_not_found(service):
    """Assign raises ClaimNotFoundError when claim does not exist."""
    with pytest.raises(ClaimNotFoundError, match="not found"):
        service.assign("CLM-NOTEXIST", "adj-1", actor_id="workflow")


def test_assign_raises_when_not_needs_review(service, repo):
    """Assign raises ValueError when claim is not in needs_review."""
    claim_input = ClaimInput(
        policy_number="POL-B",
        vin="VIN-B",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-15",
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = repo.create_claim(claim_input)
    # Claim is pending, not needs_review
    with pytest.raises(ValueError, match="not in needs_review"):
        service.assign(claim_id, "adj-1", actor_id="workflow")


def test_reject_delegates_to_repo(service, repo, temp_db):
    """Reject delegates to repo.perform_adjuster_action."""
    claim_input = ClaimInput(
        policy_number="POL-C",
        vin="VIN-C",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-15",
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = repo.create_claim(claim_input)
    with get_connection(repo._db_path) as conn:
        conn.execute(
            "UPDATE claims SET status = ? WHERE id = ?",
            (STATUS_NEEDS_REVIEW, claim_id),
        )

    service.reject(claim_id, actor_id="workflow", reason="Duplicate")
    claim = repo.get_claim(claim_id)
    assert claim["status"] == "denied"


def test_reject_raises_on_not_found(service):
    """Reject raises ClaimNotFoundError when claim does not exist."""
    with pytest.raises(ClaimNotFoundError, match="not found"):
        service.reject("CLM-NOTEXIST", actor_id="workflow")


def test_request_info_delegates_to_repo(service, repo, temp_db):
    """Request_info delegates to repo.perform_adjuster_action."""
    claim_input = ClaimInput(
        policy_number="POL-D",
        vin="VIN-D",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-15",
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = repo.create_claim(claim_input)
    with get_connection(repo._db_path) as conn:
        conn.execute(
            "UPDATE claims SET status = ? WHERE id = ?",
            (STATUS_NEEDS_REVIEW, claim_id),
        )

    service.request_info(claim_id, actor_id="workflow", note="Need photos")
    claim = repo.get_claim(claim_id)
    assert claim["status"] == "pending_info"


def test_escalate_to_siu_delegates_to_repo(service, repo, temp_db):
    """Escalate_to_siu delegates to repo.perform_adjuster_action."""
    claim_input = ClaimInput(
        policy_number="POL-E",
        vin="VIN-E",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-15",
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = repo.create_claim(claim_input)
    with get_connection(repo._db_path) as conn:
        conn.execute(
            "UPDATE claims SET status = ? WHERE id = ?",
            (STATUS_NEEDS_REVIEW, claim_id),
        )

    service.escalate_to_siu(claim_id, actor_id="workflow")
    claim = repo.get_claim(claim_id)
    assert claim["status"] == "under_investigation"


def test_approve_delegates_to_repo(service, repo, temp_db):
    """Approve delegates to repo.perform_adjuster_action (audit only, no status change)."""
    claim_input = ClaimInput(
        policy_number="POL-F",
        vin="VIN-F",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-15",
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = repo.create_claim(claim_input)
    with get_connection(repo._db_path) as conn:
        conn.execute(
            "UPDATE claims SET status = ? WHERE id = ?",
            (STATUS_NEEDS_REVIEW, claim_id),
        )

    service.approve(claim_id, actor_id="workflow")
    claim = repo.get_claim(claim_id)
    assert claim["status"] == STATUS_NEEDS_REVIEW
    history = repo.get_claim_history(claim_id)
    assert any(e["action"] == "approval" for e in history)
