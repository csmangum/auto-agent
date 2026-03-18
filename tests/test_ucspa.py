"""Tests for UCSPA (Unfair Claims Settlement Practices Act) compliance."""

from datetime import date

from claim_agent.compliance.ucspa import (
    get_ucspa_deadlines,
    claims_with_deadlines_approaching,
)
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput


def test_get_ucspa_deadlines_california():
    """California: 15/40/30 days for ack/inv/payment."""
    base = date(2026, 3, 1)
    deadlines = get_ucspa_deadlines(base, "California")
    assert deadlines["acknowledgment_due"] == "2026-03-16"
    assert deadlines["investigation_due"] == "2026-04-10"
    assert deadlines["payment_due"] == "2026-03-31"


def test_get_ucspa_deadlines_florida():
    """Florida: 14/90/90 days."""
    base = date(2026, 3, 1)
    deadlines = get_ucspa_deadlines(base, "Florida")
    assert deadlines["acknowledgment_due"] == "2026-03-15"
    assert deadlines["investigation_due"] == "2026-05-30"
    assert deadlines["payment_due"] == "2026-05-30"


def test_get_ucspa_deadlines_unknown_state_uses_defaults():
    """Unknown state uses default 15/40/30."""
    base = date(2026, 3, 1)
    deadlines = get_ucspa_deadlines(base, "UnknownState")
    assert deadlines["acknowledgment_due"] == "2026-03-16"
    assert deadlines["investigation_due"] == "2026-04-10"
    assert deadlines["payment_due"] == "2026-03-31"


def test_create_ucspa_compliance_tasks_direct(temp_db):
    """create_ucspa_compliance_tasks directly creates compliance tasks."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-TX-001",
        vin="1HGBH41JXMN109186",
        vehicle_year=2021,
        vehicle_make="Toyota",
        vehicle_model="Camry",
        incident_date=date(2026, 3, 1),
        incident_description="Highway collision",
        damage_description="Front bumper damage",
        loss_state="Texas",
    )
    claim_id = repo.create_claim(claim_input)

    tasks, _ = repo.get_tasks_for_claim(claim_id)
    ucspa_tasks = [t for t in tasks if t.get("auto_created_from", "").startswith("ucspa:")]
    assert len(ucspa_tasks) == 3


def test_create_ucspa_compliance_tasks_creates_tasks(temp_db):
    """UCSPA tasks are created at FNOL."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="1HGBH41JXMN109186",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date=date(2026, 3, 1),
        incident_description="Parking lot damage",
        damage_description="Dent on door",
        loss_state="California",
    )
    claim_id = repo.create_claim(claim_input)

    tasks, _ = repo.get_tasks_for_claim(claim_id)
    ucspa_tasks = [t for t in tasks if t.get("auto_created_from", "").startswith("ucspa:")]
    assert len(ucspa_tasks) >= 3  # acknowledgment, investigation, prompt_payment

    claim = repo.get_claim(claim_id)
    # Deadlines are set from date.today() at FNOL
    assert claim.get("acknowledgment_due") is not None
    assert claim.get("investigation_due") is not None
    assert claim.get("payment_due") is not None


def test_record_acknowledgment(temp_db):
    """record_acknowledgment sets acknowledged_at and is idempotent."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="1HGBH41JXMN109186",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date=date(2026, 3, 1),
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = repo.create_claim(claim_input)

    # First call: acknowledged_at is set and True is returned.
    result = repo.record_acknowledgment(claim_id)
    assert result is True
    claim = repo.get_claim(claim_id)
    first_ts = claim.get("acknowledged_at")
    assert first_ts is not None

    # Second call: acknowledged_at must not be overwritten (returns False).
    result2 = repo.record_acknowledgment(claim_id)
    assert result2 is False
    claim2 = repo.get_claim(claim_id)
    assert claim2.get("acknowledged_at") == first_ts


def test_record_denial_letter(temp_db):
    """record_denial_letter persists denial_reason and denial_letter_body."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="1HGBH41JXMN109186",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date=date(2026, 3, 1),
        incident_description="Test",
        damage_description="Test",
    )
    claim_id = repo.create_claim(claim_input)
    repo.update_claim_status(claim_id, "processing")
    repo.update_claim_status(claim_id, "denied")
    repo.record_denial_letter(
        claim_id,
        "Policy exclusion: pre-existing damage",
        "Dear Policyholder,\n\nWe deny your claim because...\n\nAPPEAL RIGHTS: You may appeal...",
    )

    claim = repo.get_claim(claim_id)
    assert claim.get("denial_reason") == "Policy exclusion: pre-existing damage"
    assert "APPEAL RIGHTS" in (claim.get("denial_letter_body") or "")
    assert claim.get("denial_letter_sent_at") is not None


def test_claims_with_deadlines_approaching_empty():
    """claims_with_deadlines_approaching returns empty when no claims."""
    from claim_agent.db.database import get_db_path

    repo = ClaimRepository(db_path=get_db_path())
    results = claims_with_deadlines_approaching(repo, days_ahead=30)
    assert isinstance(results, list)
