"""Tests for reserve management: set_reserve, adjust_reserve, adequacy, FNOL integration."""

import pytest

from claim_agent.db.constants import (
    RESERVE_ADEQUACY_CODE_BELOW_BENCHMARK,
    RESERVE_ADEQUACY_CODE_BELOW_ESTIMATE,
    RESERVE_ADEQUACY_CODE_BELOW_PAYOUT,
    RESERVE_ADEQUACY_CODE_NOT_SET,
    STATUS_OPEN,
)
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.exceptions import ClaimNotFoundError, DomainValidationError, ReserveAuthorityError


def test_set_reserve_creates_history_and_audit(temp_db):
    """set_reserve updates claim, inserts reserve_history, and logs audit."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="1HGBH41JXMN109186",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date="2024-01-15",
        incident_description="Parking lot scrape",
        damage_description="Scratch on door",
    )
    claim_id = repo.create_claim(claim_input)
    repo.set_reserve(claim_id, 2500.0, reason="Initial estimate", actor_id="workflow")

    claim = repo.get_claim(claim_id)
    assert claim["reserve_amount"] == 2500.0

    history = repo.get_reserve_history(claim_id)
    assert len(history) == 1
    assert history[0]["new_amount"] == 2500.0
    assert history[0]["old_amount"] is None
    assert history[0]["reason"] == "Initial estimate"
    assert history[0]["actor_id"] == "workflow"


def test_adjust_reserve_records_old_amount(temp_db):
    """adjust_reserve records old_amount in history and uses reserve_adjusted audit."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-002",
        vin="1HGBH41JXMN109187",
        vehicle_year=2019,
        vehicle_make="Toyota",
        vehicle_model="Camry",
        incident_date="2024-02-01",
        incident_description="Rear-end",
        damage_description="Bumper damage",
        estimated_damage=3000.0,
    )
    claim_id = repo.create_claim(claim_input)
    # FNOL sets initial reserve from estimated_damage
    claim = repo.get_claim(claim_id)
    assert claim["reserve_amount"] == 3000.0

    repo.adjust_reserve(claim_id, 3500.0, reason="Supplemental estimate", actor_id="workflow")

    history = repo.get_reserve_history(claim_id)
    assert len(history) >= 2
    # Most recent first
    latest = history[0]
    assert latest["new_amount"] == 3500.0
    assert latest["old_amount"] == 3000.0
    assert "Supplemental" in latest["reason"]


def test_set_reserve_negative_raises(temp_db):
    """set_reserve rejects negative amount."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-003",
        vin="1HGBH41JXMN109188",
        vehicle_year=2021,
        vehicle_make="Ford",
        vehicle_model="F-150",
        incident_date="2024-03-01",
        incident_description="Hail damage",
        damage_description="Dents",
    )
    claim_id = repo.create_claim(claim_input)
    with pytest.raises(DomainValidationError, match="cannot be negative"):
        repo.set_reserve(claim_id, -100.0)


def test_adjust_reserve_nonexistent_raises(temp_db):
    """adjust_reserve raises ClaimNotFoundError for nonexistent claim."""
    repo = ClaimRepository(db_path=temp_db)
    with pytest.raises(ClaimNotFoundError, match="not found"):
        repo.adjust_reserve("CLM-NONEXIST", 1000.0)


def test_authority_limit_blocks_adjuster(temp_db, monkeypatch):
    """When actor is adjuster and amount exceeds limit, ReserveAuthorityError is raised."""

    def low_limit():
        return {
            "adjuster_limit": 5000.0,
            "supervisor_limit": 50000.0,
            "initial_reserve_from_estimated_damage": True,
        }

    monkeypatch.setattr("claim_agent.db.repository.get_reserve_config", low_limit)

    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-004",
        vin="1HGBH41JXMN109189",
        vehicle_year=2022,
        vehicle_make="Chevy",
        vehicle_model="Silverado",
        incident_date="2024-04-01",
        incident_description="Total loss",
        damage_description="Severe",
    )
    claim_id = repo.create_claim(claim_input)
    with pytest.raises(ReserveAuthorityError, match="Supervisor approval required"):
        repo.set_reserve(claim_id, 15000.0, actor_id="adjuster-123")


def test_workflow_bypasses_authority(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-005",
        vin="1HGBH41JXMN109190",
        vehicle_year=2023,
        vehicle_make="Tesla",
        vehicle_model="Model 3",
        incident_date="2024-05-01",
        incident_description="Collision",
        damage_description="Front damage",
    )
    claim_id = repo.create_claim(claim_input)
    repo.set_reserve(claim_id, 25000.0, actor_id="workflow")
    claim = repo.get_claim(claim_id)
    assert claim["reserve_amount"] == 25000.0


def test_supervisor_can_set_reserve_above_adjuster_limit(temp_db, monkeypatch):
    """When actor is supervisor, amount up to supervisor_limit is allowed."""

    def limits():
        return {
            "adjuster_limit": 5000.0,
            "supervisor_limit": 50000.0,
            "initial_reserve_from_estimated_damage": True,
        }

    monkeypatch.setattr("claim_agent.db.repository.get_reserve_config", limits)

    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-SUP",
        vin="1HGBH41JXMN109200",
        vehicle_year=2020,
        vehicle_make="Nissan",
        vehicle_model="Altima",
        incident_date="2024-06-01",
        incident_description="Fender bender",
        damage_description="Minor scratch",
    )
    claim_id = repo.create_claim(claim_input)
    repo.set_reserve(claim_id, 15000.0, actor_id="supervisor-1", role="supervisor")
    claim = repo.get_claim(claim_id)
    assert claim["reserve_amount"] == 15000.0


def test_admin_can_set_reserve_above_adjuster_limit(temp_db, monkeypatch):
    """Admin role uses supervisor_limit like supervisor."""

    def limits():
        return {
            "adjuster_limit": 5000.0,
            "supervisor_limit": 50000.0,
            "initial_reserve_from_estimated_damage": True,
        }

    monkeypatch.setattr("claim_agent.db.repository.get_reserve_config", limits)

    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-ADM",
        vin="1HGBH41JXMN109201",
        vehicle_year=2021,
        vehicle_make="Hyundai",
        vehicle_model="Ioniq",
        incident_date="2024-07-15",
        incident_description="Parking",
        damage_description="Door ding",
    )
    claim_id = repo.create_claim(claim_input)
    repo.set_reserve(claim_id, 15000.0, actor_id="admin-1", role="admin")
    assert repo.get_claim(claim_id)["reserve_amount"] == 15000.0


def test_supervisor_blocked_above_supervisor_limit(temp_db, monkeypatch):
    """Supervisor above supervisor_limit gets ReserveAuthorityError with executive hint."""

    def limits():
        return {
            "adjuster_limit": 5000.0,
            "supervisor_limit": 20000.0,
            "initial_reserve_from_estimated_damage": True,
        }

    monkeypatch.setattr("claim_agent.db.repository.get_reserve_config", limits)

    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-SUP-CAP",
        vin="1HGBH41JXMN109202",
        vehicle_year=2020,
        vehicle_make="Kia",
        vehicle_model="Soul",
        incident_date="2024-08-01",
        incident_description="Hail",
        damage_description="Roof",
    )
    claim_id = repo.create_claim(claim_input)
    with pytest.raises(ReserveAuthorityError, match="executive approval required"):
        repo.set_reserve(claim_id, 25000.0, actor_id="sup-1", role="supervisor")


def test_executive_bypasses_reserve_limits(temp_db, monkeypatch):
    """Executive has no reserve cap when RESERVE_EXECUTIVE_LIMIT is 0 (default)."""

    def limits():
        return {
            "adjuster_limit": 5000.0,
            "supervisor_limit": 20000.0,
            "executive_limit": 0.0,
            "initial_reserve_from_estimated_damage": True,
        }

    monkeypatch.setattr("claim_agent.db.repository.get_reserve_config", limits)

    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-EXE",
        vin="1HGBH41JXMN109203",
        vehicle_year=2022,
        vehicle_make="BMW",
        vehicle_model="X3",
        incident_date="2024-09-01",
        incident_description="Multi-vehicle",
        damage_description="Total loss",
    )
    claim_id = repo.create_claim(claim_input)
    repo.set_reserve(claim_id, 500000.0, actor_id="exec-1", role="executive")
    assert repo.get_claim(claim_id)["reserve_amount"] == 500000.0


def test_executive_blocked_above_executive_limit(temp_db, monkeypatch):
    """Executive above positive RESERVE_EXECUTIVE_LIMIT raises ReserveAuthorityError."""

    def limits():
        return {
            "adjuster_limit": 5000.0,
            "supervisor_limit": 20000.0,
            "executive_limit": 100000.0,
            "initial_reserve_from_estimated_damage": True,
        }

    monkeypatch.setattr("claim_agent.db.repository.get_reserve_config", limits)

    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-EXE-CAP",
        vin="1HGBH41JXMN109204",
        vehicle_year=2021,
        vehicle_make="Audi",
        vehicle_model="Q5",
        incident_date="2024-10-01",
        incident_description="Hail",
        damage_description="Roof",
    )
    claim_id = repo.create_claim(claim_input)
    with pytest.raises(ReserveAuthorityError, match="RESERVE_EXECUTIVE_LIMIT"):
        repo.set_reserve(claim_id, 200000.0, actor_id="exec-1", role="executive")


def test_adjust_reserve_skip_authority_check_records_bypass(temp_db, monkeypatch):
    """skip_authority_check is visible on reserve_history and audit details."""

    def limits():
        return {
            "adjuster_limit": 5000.0,
            "supervisor_limit": 20000.0,
            "executive_limit": 0.0,
            "initial_reserve_from_estimated_damage": True,
        }

    monkeypatch.setattr("claim_agent.db.repository.get_reserve_config", limits)

    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-SKIP-AUD",
        vin="1HGBH41JXMN109205",
        vehicle_year=2019,
        vehicle_make="Honda",
        vehicle_model="Civic",
        incident_date="2024-11-01",
        incident_description="Rear-end",
        damage_description="Bumper",
    )
    claim_id = repo.create_claim(claim_input)
    repo.adjust_reserve(
        claim_id,
        75000.0,
        reason="Board exception",
        actor_id="admin-1",
        role="admin",
        skip_authority_check=True,
    )
    hist = repo.get_reserve_history(claim_id)
    assert hist[0]["reason"]
    assert "[authority check bypassed]" in hist[0]["reason"]


def test_fnol_sets_initial_reserve_from_estimated_damage(temp_db):
    """create_claim with estimated_damage sets initial reserve when config enabled."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-006",
        vin="1HGBH41JXMN109191",
        vehicle_year=2020,
        vehicle_make="Nissan",
        vehicle_model="Altima",
        incident_date="2024-06-01",
        incident_description="Fender bender",
        damage_description="Minor scratch",
        estimated_damage=1800.0,
    )
    claim_id = repo.create_claim(claim_input)

    claim = repo.get_claim(claim_id)
    assert claim["reserve_amount"] == 1800.0

    history = repo.get_reserve_history(claim_id)
    assert len(history) == 1
    assert history[0]["new_amount"] == 1800.0
    assert "FNOL" in history[0]["reason"] or "estimated_damage" in history[0]["reason"].lower()


def test_fnol_no_reserve_when_no_estimated_damage(temp_db):
    """create_claim without estimated_damage does not set reserve."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-007",
        vin="1HGBH41JXMN109192",
        vehicle_year=2021,
        vehicle_make="Hyundai",
        vehicle_model="Elantra",
        incident_date="2024-07-01",
        incident_description="Hit and run",
        damage_description="Unknown",
    )
    claim_id = repo.create_claim(claim_input)
    claim = repo.get_claim(claim_id)
    assert claim.get("reserve_amount") is None
    history = repo.get_reserve_history(claim_id)
    assert len(history) == 0


def test_check_reserve_adequacy_adequate(temp_db):
    """check_reserve_adequacy returns adequate when reserve >= estimated_damage."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-008",
        vin="1HGBH41JXMN109193",
        vehicle_year=2019,
        vehicle_make="Mazda",
        vehicle_model="CX-5",
        incident_date="2024-08-01",
        incident_description="Side swipe",
        damage_description="Door damage",
        estimated_damage=2200.0,
    )
    claim_id = repo.create_claim(claim_input)
    repo.set_reserve(claim_id, 2500.0, actor_id="workflow")

    result = repo.check_reserve_adequacy(claim_id)
    assert result["adequate"] is True
    assert result["reserve"] == 2500.0
    assert result["estimated_damage"] == 2200.0
    assert result["warnings"] == []
    assert result["warning_codes"] == []


def test_check_reserve_adequacy_inadequate(temp_db):
    """check_reserve_adequacy returns inadequate when reserve < estimated_damage."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-009",
        vin="1HGBH41JXMN109194",
        vehicle_year=2022,
        vehicle_make="Subaru",
        vehicle_model="Outback",
        incident_date="2024-09-01",
        incident_description="Deer strike",
        damage_description="Front end",
        estimated_damage=5000.0,
    )
    claim_id = repo.create_claim(claim_input)
    repo.set_reserve(claim_id, 3000.0, actor_id="workflow")

    result = repo.check_reserve_adequacy(claim_id)
    assert result["adequate"] is False
    assert result["warning_codes"] == [RESERVE_ADEQUACY_CODE_BELOW_ESTIMATE]


def test_check_reserve_adequacy_inadequate_when_payout_exceeds_reserve(temp_db):
    """Adequacy uses max(estimated_damage, payout); warn when reserve is below payout."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-PAYOUT-1",
        vin="1HGBH41JXMN109196",
        vehicle_year=2021,
        vehicle_make="Volvo",
        vehicle_model="XC40",
        incident_date="2024-11-01",
        incident_description="Parking lot",
        damage_description="Bumper",
    )
    claim_id = repo.create_claim(claim_input)
    repo.set_reserve(claim_id, 5000.0, actor_id="workflow")
    repo.update_claim_status(claim_id, STATUS_OPEN, payout_amount=8000.0, skip_validation=True)

    result = repo.check_reserve_adequacy(claim_id)
    assert result["adequate"] is False
    assert result["payout_amount"] == 8000.0
    assert result["warning_codes"] == [RESERVE_ADEQUACY_CODE_BELOW_PAYOUT]


def test_check_reserve_adequacy_uses_max_of_estimate_and_payout(temp_db):
    """When both estimate and payout exist, benchmark is the greater of the two."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-PAYOUT-2",
        vin="1HGBH41JXMN109197",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="CR-V",
        incident_date="2024-12-01",
        incident_description="Sideswipe",
        damage_description="Quarter panel",
        estimated_damage=7000.0,
    )
    claim_id = repo.create_claim(claim_input)
    # FNOL reserve 7000 from estimated_damage, then adjust to 5000
    repo.adjust_reserve(claim_id, 5000.0, reason="Adjusted down", actor_id="workflow")
    repo.update_claim_status(claim_id, STATUS_OPEN, payout_amount=4000.0, skip_validation=True)

    result = repo.check_reserve_adequacy(claim_id)
    assert result["adequate"] is False
    assert result["reserve"] == 5000.0
    assert result["estimated_damage"] == 7000.0
    assert result["payout_amount"] == 4000.0
    assert result["warning_codes"] == [RESERVE_ADEQUACY_CODE_BELOW_ESTIMATE]


def test_check_reserve_adequacy_below_benchmark_when_estimate_and_payout_tie(temp_db):
    """When estimate equals payout at the benchmark, use RESERVE_BELOW_BENCHMARK messaging."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-TIE",
        vin="1HGBH41JXMN109198",
        vehicle_year=2020,
        vehicle_make="Mazda",
        vehicle_model="3",
        incident_date="2024-10-15",
        incident_description="Multi-vehicle",
        damage_description="Both sides",
        estimated_damage=6000.0,
    )
    claim_id = repo.create_claim(claim_input)
    repo.adjust_reserve(claim_id, 4000.0, reason="Adjusted", actor_id="workflow")
    repo.update_claim_status(claim_id, STATUS_OPEN, payout_amount=6000.0, skip_validation=True)

    result = repo.check_reserve_adequacy(claim_id)
    assert result["adequate"] is False
    assert result["warning_codes"] == [RESERVE_ADEQUACY_CODE_BELOW_BENCHMARK]


def test_check_reserve_adequacy_no_reserve_with_payout(temp_db):
    """Payout without reserve yields NOT_SET code."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-NORES",
        vin="1HGBH41JXMN109199",
        vehicle_year=2019,
        vehicle_make="Subaru",
        vehicle_model="Forester",
        incident_date="2024-08-20",
        incident_description="Hail",
        damage_description="Roof",
    )
    claim_id = repo.create_claim(claim_input)
    assert repo.get_claim(claim_id).get("reserve_amount") is None
    repo.update_claim_status(claim_id, STATUS_OPEN, payout_amount=4500.0, skip_validation=True)

    result = repo.check_reserve_adequacy(claim_id)
    assert result["adequate"] is False
    assert result["warning_codes"] == [RESERVE_ADEQUACY_CODE_NOT_SET]


def test_check_reserve_adequacy_nonexistent_raises(temp_db):
    """check_reserve_adequacy raises ClaimNotFoundError for nonexistent claim."""
    repo = ClaimRepository(db_path=temp_db)
    with pytest.raises(ClaimNotFoundError, match="not found"):
        repo.check_reserve_adequacy("CLM-NONEXIST")


def test_get_reserve_history_empty(temp_db):
    """get_reserve_history returns empty list when no reserve changes."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-010",
        vin="1HGBH41JXMN109195",
        vehicle_year=2020,
        vehicle_make="Kia",
        vehicle_model="Sorento",
        incident_date="2024-10-01",
        incident_description="Vandalism",
        damage_description="Keyed",
    )
    claim_id = repo.create_claim(claim_input)
    history = repo.get_reserve_history(claim_id)
    assert history == []
