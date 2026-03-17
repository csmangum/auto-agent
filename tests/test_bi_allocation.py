"""Tests for BI coverage limit allocation."""

import pytest

from claim_agent.models.incident import (
    BIAllocationInput,
    ClaimantDemandInput,
)
from claim_agent.services.bi_allocation import allocate_bi_limits


def test_allocate_bi_empty_demands():
    """Empty demands returns zero totals and no allocations."""
    inp = BIAllocationInput(
        claim_id="CLM-001",
        claimant_demands=[],
        bi_per_accident_limit=50000.0,
    )
    result = allocate_bi_limits(inp)
    assert result.claim_id == "CLM-001"
    assert result.total_demanded == 0
    assert result.total_allocated == 0
    assert result.limit_exceeded is False
    assert result.allocations == []


def test_allocate_bi_limit_not_exceeded():
    """When total demands <= limit, each claimant gets full demand."""
    inp = BIAllocationInput(
        claim_id="CLM-001",
        claimant_demands=[
            ClaimantDemandInput(claimant_id="P1", demanded_amount=20000.0),
            ClaimantDemandInput(claimant_id="P2", demanded_amount=15000.0),
        ],
        bi_per_accident_limit=50000.0,
    )
    result = allocate_bi_limits(inp)
    assert result.total_demanded == 35000.0
    assert result.total_allocated == 35000.0
    assert result.limit_exceeded is False
    assert len(result.allocations) == 2
    assert result.allocations[0]["allocated"] == 20000.0
    assert result.allocations[0]["shortfall"] == 0
    assert result.allocations[1]["allocated"] == 15000.0
    assert result.allocations[1]["shortfall"] == 0


def test_allocate_bi_proportional():
    """Proportional allocation when limit exceeded."""
    inp = BIAllocationInput(
        claim_id="CLM-001",
        claimant_demands=[
            ClaimantDemandInput(claimant_id="P1", demanded_amount=60000.0),
            ClaimantDemandInput(claimant_id="P2", demanded_amount=40000.0),
        ],
        bi_per_accident_limit=50000.0,
        allocation_method="proportional",
    )
    result = allocate_bi_limits(inp)
    assert result.total_demanded == 100000.0
    assert result.total_allocated == 50000.0
    assert result.limit_exceeded is True
    assert len(result.allocations) == 2
    assert result.allocations[0]["allocated"] == pytest.approx(30000.0)
    assert result.allocations[0]["shortfall"] == pytest.approx(30000.0)
    assert result.allocations[1]["allocated"] == pytest.approx(20000.0)
    assert result.allocations[1]["shortfall"] == pytest.approx(20000.0)


def test_allocate_bi_equal():
    """Equal allocation splits limit equally among claimants."""
    inp = BIAllocationInput(
        claim_id="CLM-001",
        claimant_demands=[
            ClaimantDemandInput(claimant_id="P1", demanded_amount=10000.0),
            ClaimantDemandInput(claimant_id="P2", demanded_amount=15000.0),
            ClaimantDemandInput(claimant_id="P3", demanded_amount=25000.0),
        ],
        bi_per_accident_limit=30000.0,
        allocation_method="equal",
    )
    result = allocate_bi_limits(inp)
    assert result.total_demanded == 50000.0
    assert result.total_allocated == 30000.0
    assert result.limit_exceeded is True
    assert len(result.allocations) == 3
    assert result.allocations[0]["allocated"] == 10000.0
    assert result.allocations[0]["shortfall"] == 0
    assert result.allocations[1]["allocated"] == 10000.0
    assert result.allocations[1]["shortfall"] == 5000.0
    assert result.allocations[2]["allocated"] == 10000.0
    assert result.allocations[2]["shortfall"] == 15000.0


def test_allocate_bi_severity_weighted():
    """Severity-weighted allocation favors higher severity claimants."""
    inp = BIAllocationInput(
        claim_id="CLM-001",
        claimant_demands=[
            ClaimantDemandInput(
                claimant_id="P1",
                demanded_amount=50000.0,
                injury_severity=2.0,
            ),
            ClaimantDemandInput(
                claimant_id="P2",
                demanded_amount=50000.0,
                injury_severity=1.0,
            ),
        ],
        bi_per_accident_limit=30000.0,
        allocation_method="severity_weighted",
    )
    result = allocate_bi_limits(inp)
    assert result.total_demanded == 100000.0
    assert result.total_allocated == 30000.0
    assert result.limit_exceeded is True
    assert len(result.allocations) == 2
    assert result.allocations[0]["allocated"] == pytest.approx(20000.0)
    assert result.allocations[1]["allocated"] == pytest.approx(10000.0)


def test_allocate_bi_party_id_fallback():
    """party_id is used when claimant_id not set."""
    inp = BIAllocationInput(
        claim_id="CLM-001",
        claimant_demands=[
            ClaimantDemandInput(party_id="PARTY-A", demanded_amount=10000.0),
        ],
        bi_per_accident_limit=50000.0,
    )
    result = allocate_bi_limits(inp)
    assert result.allocations[0]["claimant_id"] == "PARTY-A"


def test_claimant_demand_input_validation():
    """ClaimantDemandInput validates demanded_amount and injury_severity."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClaimantDemandInput(claimant_id="P1", demanded_amount=-100.0)

    with pytest.raises(ValidationError):
        ClaimantDemandInput(
            claimant_id="P1",
            demanded_amount=10000.0,
            injury_severity=15.0,
        )
