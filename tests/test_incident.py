"""Tests for incident-level and multi-vehicle claim support."""

from datetime import date

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.incident_repository import IncidentRepository
from claim_agent.models.incident import (
    BIAllocationInput,
    IncidentInput,
    VehicleClaimInput,
)
from claim_agent.services.bi_allocation import allocate_bi_limits


@pytest.fixture
def temp_db(tmp_path):
    """Temporary database with schema."""
    db_path = tmp_path / "claims.db"
    init_db(str(db_path))
    return str(db_path)


def test_create_incident_single_vehicle(temp_db):
    """Create incident with one vehicle produces one claim."""
    repo = IncidentRepository(db_path=temp_db)
    incident_input = IncidentInput(
        incident_date=date(2025, 3, 15),
        incident_description="Single car hit a tree",
        vehicles=[
            VehicleClaimInput(
                policy_number="POL-001",
                vin="1HGBH41JXMN109186",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Accord",
                damage_description="Front end damage",
                estimated_damage=5000,
            ),
        ],
    )
    incident_id, claim_ids = repo.create_incident(incident_input)
    assert incident_id.startswith("INC-")
    assert len(claim_ids) == 1
    claim = repo.get_claims_by_incident(incident_id)[0]
    assert claim["incident_id"] == incident_id
    assert claim["policy_number"] == "POL-001"
    assert claim["vin"] == "1HGBH41JXMN109186"


def test_create_incident_multi_vehicle(temp_db):
    """Create incident with two vehicles produces two claims linked as same_incident."""
    repo = IncidentRepository(db_path=temp_db)
    incident_input = IncidentInput(
        incident_date=date(2025, 3, 15),
        incident_description="Two-car collision at intersection",
        loss_state="CA",
        vehicles=[
            VehicleClaimInput(
                policy_number="POL-001",
                vin="1HGBH41JXMN109186",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Accord",
                damage_description="Front bumper damage",
                estimated_damage=3000,
            ),
            VehicleClaimInput(
                policy_number="POL-002",
                vin="2HGFG3B54CH501234",
                vehicle_year=2022,
                vehicle_make="Toyota",
                vehicle_model="Camry",
                damage_description="Rear damage",
                estimated_damage=4500,
            ),
        ],
    )
    incident_id, claim_ids = repo.create_incident(incident_input)
    assert len(claim_ids) == 2
    claims = repo.get_claims_by_incident(incident_id)
    assert len(claims) == 2
    # Claims should be linked
    related = repo.get_related_claims(claim_ids[0], link_type="same_incident")
    assert claim_ids[1] in related


def test_create_claim_link(temp_db):
    """Create link between two claims for cross-carrier coordination."""
    repo = IncidentRepository(db_path=temp_db)
    incident_input = IncidentInput(
        incident_date=date(2025, 3, 15),
        incident_description="Two-car accident",
        vehicles=[
            VehicleClaimInput(
                policy_number="POL-001",
                vin="VIN1",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Accord",
                damage_description="Front damage",
            ),
            VehicleClaimInput(
                policy_number="POL-002",
                vin="VIN2",
                vehicle_year=2021,
                vehicle_make="Toyota",
                vehicle_model="Camry",
                damage_description="Rear damage",
            ),
        ],
    )
    _, claim_ids = repo.create_incident(incident_input)
    link_id = repo.create_claim_link(
        claim_ids[0],
        claim_ids[1],
        "opposing_carrier",
        opposing_carrier="Other Insurance Co",
    )
    assert link_id > 0
    related = repo.get_related_claims(claim_ids[0])
    assert claim_ids[1] in related


def test_bi_allocation_under_limit():
    """When demands are under limit, each claimant gets full amount."""
    result = allocate_bi_limits(
        BIAllocationInput(
            claim_id="CLM-123",
            claimant_demands=[
                {"claimant_id": "c1", "demanded_amount": 50000},
                {"claimant_id": "c2", "demanded_amount": 30000},
            ],
            bi_per_accident_limit=100000,
        )
    )
    assert result.limit_exceeded is False
    assert result.total_demanded == 80000
    assert result.total_allocated == 80000
    assert result.allocations[0]["allocated"] == 50000
    assert result.allocations[1]["allocated"] == 30000


def test_bi_allocation_over_limit_proportional():
    """When demands exceed limit, proportional allocation applies."""
    result = allocate_bi_limits(
        BIAllocationInput(
            claim_id="CLM-123",
            claimant_demands=[
                {"claimant_id": "c1", "demanded_amount": 100000},
                {"claimant_id": "c2", "demanded_amount": 50000},
            ],
            bi_per_accident_limit=100000,
            allocation_method="proportional",
        )
    )
    assert result.limit_exceeded is True
    assert result.total_demanded == 150000
    assert result.total_allocated == pytest.approx(100000, rel=0.01)
    # c1 gets 2/3, c2 gets 1/3
    assert result.allocations[0]["allocated"] == pytest.approx(66666.67, abs=0.01)
    assert result.allocations[1]["allocated"] == pytest.approx(33333.33, abs=0.01)
    assert result.allocations[0]["shortfall"] > 0
    assert result.allocations[1]["shortfall"] > 0


def test_bi_allocation_equal():
    """Equal allocation splits limit evenly."""
    result = allocate_bi_limits(
        BIAllocationInput(
            claim_id="CLM-123",
            claimant_demands=[
                {"claimant_id": "c1", "demanded_amount": 80000},
                {"claimant_id": "c2", "demanded_amount": 60000},
            ],
            bi_per_accident_limit=100000,
            allocation_method="equal",
        )
    )
    assert result.limit_exceeded is True
    assert result.total_allocated == 100000
    assert result.allocations[0]["allocated"] == 50000
    assert result.allocations[1]["allocated"] == 50000


def test_bi_allocation_severity_weighted():
    """Severity weighted allocation distributes by injury severity weights."""
    result = allocate_bi_limits(
        BIAllocationInput(
            claim_id="CLM-123",
            claimant_demands=[
                {"claimant_id": "c1", "demanded_amount": 100000, "injury_severity": 1.0},
                {"claimant_id": "c2", "demanded_amount": 100000, "injury_severity": 1.0},
            ],
            bi_per_accident_limit=80000,
            allocation_method="severity_weighted",
        )
    )
    assert result.limit_exceeded is True
    # Should allocate full 80000, not under-allocate due to in-loop mutation bug
    assert result.total_allocated == pytest.approx(80000, abs=1)
    # Equal weights should split 50/50
    assert result.allocations[0]["allocated"] == pytest.approx(40000, abs=1)
    assert result.allocations[1]["allocated"] == pytest.approx(40000, abs=1)
