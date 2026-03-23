"""Tests for IncidentRepository: incident creation, rollback, claim links."""

from datetime import date
from unittest.mock import patch

import pytest

from sqlalchemy import text

from claim_agent.db.audit_events import ACTOR_WORKFLOW
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
    """Partial failure rolls back entire transaction: no incident or claims remain.

    ``create_incident`` now uses a single transaction, so a failure on any
    step causes an automatic rollback of all writes without needing compensating
    cleanup steps.
    """
    incident_input = IncidentInput(
        incident_date=date(2025, 1, 15),
        incident_description="Rollback test",
        vehicles=[
            _make_vehicle("POL-001", "VIN001"),
            _make_vehicle("POL-002", "VIN002"),
        ],
    )

    original_create_in_tx = ClaimRepository.create_claim_in_transaction
    call_count = 0

    def mock_create_in_tx(self, conn, claim_input, *, actor_id=ACTOR_WORKFLOW, policy=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return original_create_in_tx(self, conn, claim_input, actor_id=actor_id, policy=policy)
        raise ValueError("Simulated failure")

    with patch.object(ClaimRepository, "create_claim_in_transaction", mock_create_in_tx):
        with pytest.raises(ValueError, match="Simulated failure"):
            incident_repo.create_incident(incident_input)

    # The entire transaction was rolled back: no incidents and no claims should exist.
    with get_connection(incident_repo._db_path) as conn:
        incidents = conn.execute(text("SELECT id FROM incidents")).fetchall()
        assert len(incidents) == 0
        all_claims = conn.execute(text("SELECT id FROM claims")).fetchall()
        assert len(all_claims) == 0


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
            text(
                "INSERT INTO incidents (id, incident_date, incident_description) "
                "VALUES (:id, :incident_date, :incident_description)"
            ),
            {"id": "INC-ROLLBACK", "incident_date": "2025-01-15", "incident_description": "Test"},
        )
        conn.execute(
            text("UPDATE claims SET incident_id = :incident_id WHERE id = :id"),
            {"incident_id": "INC-ROLLBACK", "id": claim_id},
        )

    incident_repo._rollback_incident("INC-ROLLBACK", [claim_id])

    with get_connection(incident_repo._db_path) as conn:
        incidents = conn.execute(text("SELECT id FROM incidents")).fetchall()
        assert len(incidents) == 0
        row = conn.execute(
            text("SELECT status, incident_id FROM claims WHERE id = :claim_id"),
            {"claim_id": claim_id},
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


def test_create_incident_atomic_no_partial_on_link_failure(incident_repo):
    """Failure while creating a claim link leaves no partial incident or claims.

    This validates the single-transaction guarantee: even a failure during
    the link-creation phase (after the first claim is already inserted into
    the transaction's write-set) results in a full rollback.
    """
    incident_input = IncidentInput(
        incident_date=date(2025, 1, 15),
        incident_description="Link failure rollback test",
        vehicles=[
            _make_vehicle("POL-001", "VIN001"),
            _make_vehicle("POL-002", "VIN002"),
        ],
    )

    def mock_link_in_conn(self, conn, claim_id_a, claim_id_b, link_type, opposing_carrier, notes):
        raise RuntimeError("Simulated link failure")

    with patch.object(IncidentRepository, "_create_link_in_conn", mock_link_in_conn):
        with pytest.raises(RuntimeError, match="Simulated link failure"):
            incident_repo.create_incident(incident_input)

    # Transaction rolled back: database must be empty.
    with get_connection(incident_repo._db_path) as conn:
        assert len(conn.execute(text("SELECT id FROM incidents")).fetchall()) == 0
        assert len(conn.execute(text("SELECT id FROM claims")).fetchall()) == 0
        assert len(conn.execute(text("SELECT * FROM claim_links")).fetchall()) == 0
