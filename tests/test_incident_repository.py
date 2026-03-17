"""Tests for IncidentRepository: incident creation, rollback, claim links."""

from datetime import date
from unittest.mock import patch

import pytest

from claim_agent.db.database import get_connection
from claim_agent.db.incident_repository import IncidentRepository
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.models.incident import IncidentInput, VehicleClaimInput


@pytest.fixture
def incident_repo(temp_db):
    return IncidentRepository(db_path=temp_db)


def _make_vehicle(policy: str = "POL-001", vin: str = "VIN001") -> VehicleClaimInput:
    return VehicleClaimInput(
        policy_number=policy,
        vin=vin,
        vehicle_year=2021,
        vehicle_make="Honda",
        vehicle_model="Accord",
        damage_description="Rear bumper damage",
        estimated_damage=2500.0,
    )


def test_create_incident_success(incident_repo):
    """Create incident with one vehicle produces incident and claim."""
    incident_input = IncidentInput(
        incident_date=date(2025, 1, 15),
        incident_description="Two-car collision at intersection",
        loss_state="CA",
        vehicles=[_make_vehicle()],
    )
    incident_id, claim_ids = incident_repo.create_incident(incident_input)
    assert incident_id.startswith("INC-")
    assert len(claim_ids) == 1
    assert claim_ids[0].startswith("CLM-")

    incident = incident_repo.get_incident(incident_id)
    assert incident is not None
    assert incident["incident_date"] == "2025-01-15"
    assert incident["incident_description"] == "Two-car collision at intersection"
    assert incident["loss_state"] == "CA"

    claims = incident_repo.get_claims_by_incident(incident_id)
    assert len(claims) == 1
    assert claims[0]["incident_id"] == incident_id


def test_create_incident_multiple_vehicles(incident_repo):
    """Create incident with multiple vehicles produces multiple claims and links."""
    incident_input = IncidentInput(
        incident_date=date(2025, 1, 15),
        incident_description="Multi-vehicle pileup",
        vehicles=[
            _make_vehicle("POL-001", "VIN001"),
            _make_vehicle("POL-002", "VIN002"),
            _make_vehicle("POL-003", "VIN003"),
        ],
    )
    incident_id, claim_ids = incident_repo.create_incident(incident_input)
    assert len(claim_ids) == 3

    claims = incident_repo.get_claims_by_incident(incident_id)
    assert len(claims) == 3

    related = incident_repo.get_related_claims(claim_ids[0])
    assert set(related) == {claim_ids[1], claim_ids[2]}


def test_create_incident_rollback_on_failure(incident_repo):
    """Partial failure triggers rollback: incident and claims cleaned up."""
    incident_input = IncidentInput(
        incident_date=date(2025, 1, 15),
        incident_description="Rollback test",
        vehicles=[
            _make_vehicle("POL-001", "VIN001"),
            _make_vehicle("POL-002", "VIN002"),
        ],
    )

    original_create = ClaimRepository.create_claim
    call_count = 0

    def mock_create_impl(self, claim_input, *, actor_id="system"):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_create(self, claim_input, actor_id=actor_id)
        raise ValueError("Simulated failure")

    with patch.object(ClaimRepository, "create_claim", mock_create_impl):
        with pytest.raises(ValueError, match="Simulated failure"):
            incident_repo.create_incident(incident_input)

    with get_connection(incident_repo._db_path) as conn:
        incidents = conn.execute("SELECT id FROM incidents").fetchall()
        assert len(incidents) == 0
        claims_with_incident = conn.execute(
            "SELECT id FROM claims WHERE incident_id IS NOT NULL"
        ).fetchall()
        assert len(claims_with_incident) == 0


def test_rollback_clears_incident_id_before_delete(incident_repo):
    """Rollback sets incident_id=NULL on claims before deleting incident (FK constraint)."""
    claim_repo = ClaimRepository(db_path=incident_repo._db_path)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="VIN001",
        vehicle_year=2021,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date=date(2025, 1, 15),
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = claim_repo.create_claim(claim_input)

    with get_connection(incident_repo._db_path) as conn:
        conn.execute(
            "INSERT INTO incidents (id, incident_date, incident_description) VALUES (?, ?, ?)",
            ("INC-ROLLBACK", "2025-01-15", "Test"),
        )
        conn.execute(
            "UPDATE claims SET incident_id = ? WHERE id = ?",
            ("INC-ROLLBACK", claim_id),
        )

    incident_repo._rollback_incident("INC-ROLLBACK", [claim_id])

    with get_connection(incident_repo._db_path) as conn:
        incidents = conn.execute("SELECT id FROM incidents").fetchall()
        assert len(incidents) == 0
        row = conn.execute(
            "SELECT status, incident_id FROM claims WHERE id = ?", (claim_id,)
        ).fetchone()
        assert row[0] == "failed"
        assert row[1] is None


def test_create_claim_link(incident_repo):
    """Create link between two claims."""
    claim_repo = ClaimRepository(db_path=incident_repo._db_path)
    c1 = claim_repo.create_claim(
        ClaimInput(
            policy_number="POL-001",
            vin="VIN001",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Test",
            damage_description="Test",
        )
    )
    c2 = claim_repo.create_claim(
        ClaimInput(
            policy_number="POL-002",
            vin="VIN002",
            vehicle_year=2020,
            vehicle_make="Toyota",
            vehicle_model="Camry",
            incident_date=date(2025, 1, 15),
            incident_description="Test",
            damage_description="Test",
        )
    )

    link_id = incident_repo.create_claim_link(
        c1, c2, "opposing_carrier", opposing_carrier="Acme Insurance"
    )
    assert link_id is not None

    related = incident_repo.get_related_claims(c1)
    assert c2 in related


def test_create_claim_link_duplicate_returns_none(incident_repo):
    """Creating duplicate link returns None."""
    claim_repo = ClaimRepository(db_path=incident_repo._db_path)
    c1 = claim_repo.create_claim(
        ClaimInput(
            policy_number="POL-001",
            vin="VIN001",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Test",
            damage_description="Test",
        )
    )
    c2 = claim_repo.create_claim(
        ClaimInput(
            policy_number="POL-002",
            vin="VIN002",
            vehicle_year=2020,
            vehicle_make="Toyota",
            vehicle_model="Camry",
            incident_date=date(2025, 1, 15),
            incident_description="Test",
            damage_description="Test",
        )
    )

    first = incident_repo.create_claim_link(c1, c2, "same_incident")
    second = incident_repo.create_claim_link(c1, c2, "same_incident")
    assert first is not None
    assert second is None


def test_get_incident_not_found(incident_repo):
    """get_incident returns None for non-existent incident."""
    assert incident_repo.get_incident("INC-NOTFOUND") is None
