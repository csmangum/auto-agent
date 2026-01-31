"""Tests for database and ClaimRepository."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from claim_agent.db.database import get_db_path, get_connection, init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput


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


def test_get_db_path_default():
    """Default path is data/claims.db when env unset."""
    if "CLAIMS_DB_PATH" in os.environ:
        del os.environ["CLAIMS_DB_PATH"]
    assert get_db_path() == "data/claims.db"


def test_get_db_path_env():
    """CLAIMS_DB_PATH env overrides default."""
    os.environ["CLAIMS_DB_PATH"] = "/tmp/custom.db"
    try:
        assert get_db_path() == "/tmp/custom.db"
    finally:
        del os.environ["CLAIMS_DB_PATH"]


def test_init_db_creates_tables(temp_db):
    """init_db creates claims, claim_audit_log, workflow_runs tables."""
    with get_connection(temp_db) as conn:
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cur.fetchall()]
    assert "claims" in tables
    assert "claim_audit_log" in tables
    assert "workflow_runs" in tables


def test_repository_create_claim(temp_db):
    """ClaimRepository.create_claim inserts a claim and returns claim_id."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="1HGBH41JXMN109186",
        vehicle_year=2021,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date="2025-01-15",
        incident_description="Rear-ended at stoplight.",
        damage_description="Rear bumper and trunk damage.",
    )
    claim_id = repo.create_claim(claim_input)
    assert claim_id.startswith("CLM-")
    assert len(claim_id) == len("CLM-") + 8


def test_repository_get_claim(temp_db):
    """ClaimRepository.get_claim returns the claim or None."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-002",
        vin="VIN999",
        vehicle_year=2020,
        vehicle_make="Toyota",
        vehicle_model="Camry",
        incident_date="2025-02-01",
        incident_description="Hit and run.",
        damage_description="Front fender.",
    )
    claim_id = repo.create_claim(claim_input)
    claim = repo.get_claim(claim_id)
    assert claim is not None
    assert claim["id"] == claim_id
    assert claim["policy_number"] == "POL-002"
    assert claim["vin"] == "VIN999"
    assert claim["status"] == "pending"

    assert repo.get_claim("CLM-NONEXIST") is None


def test_repository_update_claim_status(temp_db):
    """ClaimRepository.update_claim_status updates status and logs audit."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="VIN1",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-10",
        incident_description="Scratch.",
        damage_description="Door scratch.",
    )
    claim_id = repo.create_claim(claim_input)
    repo.update_claim_status(claim_id, "open", details="Intake complete")
    claim = repo.get_claim(claim_id)
    assert claim["status"] == "open"

    history = repo.get_claim_history(claim_id)
    assert len(history) >= 2
    actions = [h["action"] for h in history]
    assert "created" in actions
    assert "status_changed" in actions


def test_repository_save_workflow_result(temp_db):
    """ClaimRepository.save_workflow_result inserts into workflow_runs."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="VIN1",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-10",
        incident_description="Scratch.",
        damage_description="Door scratch.",
    )
    claim_id = repo.create_claim(claim_input)
    repo.save_workflow_result(
        claim_id,
        "new",
        "router: new",
        "Workflow completed.",
    )
    with get_connection(temp_db) as conn:
        row = conn.execute(
            "SELECT claim_id, claim_type, router_output, workflow_output FROM workflow_runs WHERE claim_id = ?",
            (claim_id,),
        ).fetchone()
    assert row is not None
    assert row["claim_type"] == "new"
    assert "Workflow completed" in row["workflow_output"]


def test_repository_get_claim_history(temp_db):
    """ClaimRepository.get_claim_history returns audit entries in order."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="VIN1",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2025-01-10",
        incident_description="Scratch.",
        damage_description="Door scratch.",
    )
    claim_id = repo.create_claim(claim_input)
    repo.update_claim_status(claim_id, "processing")
    repo.update_claim_status(claim_id, "open")

    history = repo.get_claim_history(claim_id)
    assert len(history) == 3
    assert history[0]["action"] == "created"
    assert history[1]["action"] == "status_changed"
    assert history[2]["action"] == "status_changed"
    assert history[2]["new_status"] == "open"


def test_repository_search_claims(temp_db):
    """ClaimRepository.search_claims finds by vin and/or incident_date."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="1HGBH41JXMN109186",
        vehicle_year=2021,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date="2025-01-15",
        incident_description="Rear-ended.",
        damage_description="Bumper.",
    )
    repo.create_claim(claim_input)

    matches = repo.search_claims(vin="1HGBH41JXMN109186", incident_date="2025-01-15")
    assert len(matches) == 1
    assert matches[0]["vin"] == "1HGBH41JXMN109186"
    assert matches[0]["incident_date"] == "2025-01-15"

    empty = repo.search_claims(vin="UNKNOWN", incident_date="2020-01-01")
    assert empty == []

    by_vin = repo.search_claims(vin="1HGBH41JXMN109186")
    assert len(by_vin) == 1

    by_date = repo.search_claims(incident_date="2025-01-15")
    assert len(by_date) == 1


def test_repository_search_claims_empty_criteria(temp_db):
    """Search with both None returns []."""
    repo = ClaimRepository(db_path=temp_db)
    result = repo.search_claims(vin=None, incident_date=None)
    assert result == []
