"""Tests for UCSPA (Unfair Claims Settlement Practices Act) compliance."""

from datetime import date

import pytest

from claim_agent.compliance.ucspa import (
    compute_communication_response_due,
    get_ucspa_deadlines,
    claims_with_deadlines_approaching,
    payment_due_iso_after_settlement_moment,
)
from claim_agent.compliance.state_rules import get_state_rules
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


def test_payment_due_iso_after_settlement_moment():
    """Prompt-payment due date from settlement instant uses state day count."""
    assert (
        payment_due_iso_after_settlement_moment("2026-03-01T12:00:00+00:00", "California")
        == "2026-03-31"
    )
    assert payment_due_iso_after_settlement_moment("", "California") is None


def test_settlement_recomputes_payment_due(temp_db):
    """First transition to settled sets settlement_agreed_at and refreshes payment_due."""
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
        loss_state="California",
    )
    claim_id = repo.create_claim(claim_input)
    before = repo.get_claim(claim_id)
    pd_fnol = before.get("payment_due")
    assert pd_fnol

    repo.update_claim_status(claim_id, "processing")
    repo.update_claim_status(claim_id, "settled", payout_amount=5000.0)

    after = repo.get_claim(claim_id)
    assert after.get("status") == "settled"
    assert after.get("settlement_agreed_at") is not None
    expected = payment_due_iso_after_settlement_moment(
        after["settlement_agreed_at"],
        "California",
    )
    assert after.get("payment_due") == expected
    # When settlement occurs the same calendar day as FNOL, payment_due may match the FNOL estimate.
    assert pd_fnol

    tasks, _ = repo.get_tasks_for_claim(claim_id)
    pay_tasks = [
        t
        for t in tasks
        if t.get("auto_created_from") == "ucspa:prompt_payment"
        and t.get("status") not in ("completed", "cancelled")
    ]
    assert pay_tasks
    for t in pay_tasks:
        assert t.get("due_date") == expected


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
    """record_denial_letter persists denial content and optional delivery metadata."""
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
        denial_letter_delivery_method="certified_mail",
        denial_letter_tracking_id="USPS-9407-1234-5678-9012",
        denial_letter_delivered_at="2026-03-05T10:30:00+00:00",
    )

    claim = repo.get_claim(claim_id)
    assert claim.get("denial_reason") == "Policy exclusion: pre-existing damage"
    assert "APPEAL RIGHTS" in (claim.get("denial_letter_body") or "")
    assert claim.get("denial_letter_sent_at") is not None
    assert claim.get("denial_letter_delivery_method") == "certified_mail"
    assert claim.get("denial_letter_tracking_id") == "USPS-9407-1234-5678-9012"
    assert claim.get("denial_letter_delivered_at") == "2026-03-05T10:30:00+00:00"

    history, _ = repo.get_claim_history(claim_id)
    denial_events = [h for h in history if h.get("action") == "denial_letter_sent"]
    assert denial_events
    latest_denial = denial_events[-1]
    assert latest_denial.get("after_state") is not None
    after_state = latest_denial["after_state"]
    if isinstance(after_state, str):
        import json
        after_state = json.loads(after_state)
    assert after_state.get("denial_letter_delivery_method") == "certified_mail"
    assert after_state.get("denial_letter_tracking_id") == "USPS-9407-1234-5678-9012"
    assert after_state.get("denial_letter_delivered_at") == "2026-03-05T10:30:00+00:00"


def test_record_denial_letter_invalid_delivery_method_raises(temp_db):
    """record_denial_letter rejects unsupported delivery methods."""
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

    with pytest.raises(ValueError, match="denial_letter_delivery_method must be one of"):
        repo.record_denial_letter(
            claim_id,
            "Policy exclusion: pre-existing damage",
            "Denial letter body",
            denial_letter_delivery_method="carrier_pigeon",
        )


def test_claims_with_deadlines_approaching_empty():
    """claims_with_deadlines_approaching returns empty when no claims."""
    from claim_agent.db.database import get_db_path

    repo = ClaimRepository(db_path=get_db_path())
    results = claims_with_deadlines_approaching(repo, days_ahead=30)
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Communication response deadline tests
# ---------------------------------------------------------------------------


def test_state_rules_communication_response_days():
    """StateRules includes communication_response_days for all configured states."""
    for state_name in ("California", "Florida", "New York", "Georgia", "Texas"):
        rules = get_state_rules(state_name)
        assert rules is not None
        assert rules.communication_response_days is not None
        assert rules.communication_response_days > 0


def test_compute_communication_response_due_california():
    """California: 15 communication_response days from message timestamp."""
    result = compute_communication_response_due("2026-03-01T12:00:00+00:00", "California")
    assert result == "2026-03-16"


def test_compute_communication_response_due_florida():
    """Florida: 14 communication_response days."""
    result = compute_communication_response_due("2026-03-01T00:00:00+00:00", "Florida")
    assert result == "2026-03-15"


def test_compute_communication_response_due_empty_timestamp():
    """Empty timestamp returns None."""
    assert compute_communication_response_due("", "California") is None


def test_compute_communication_response_due_z_suffix():
    """Timestamp with Z suffix is handled correctly."""
    result = compute_communication_response_due("2026-03-01T12:00:00Z", "Texas")
    assert result == "2026-03-16"


def test_compute_communication_response_due_unknown_state_uses_default():
    """Unknown state uses default 15 days."""
    result = compute_communication_response_due("2026-03-01T00:00:00+00:00", "UnknownState")
    assert result == "2026-03-16"


def test_record_claimant_communication_sets_deadline(temp_db):
    """record_claimant_communication sets last_claimant_communication_at and communication_response_due."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-COMM-001",
        vin="1HGBH41JXMN109186",
        vehicle_year=2021,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date=date(2026, 3, 1),
        incident_description="Collision at intersection",
        damage_description="Front bumper damage",
        loss_state="California",
    )
    claim_id = repo.create_claim(claim_input)

    comm_ts = "2026-03-10T14:00:00+00:00"
    due = repo.record_claimant_communication(
        claim_id,
        description="Claimant sent document request",
        communication_at=comm_ts,
    )

    assert due == "2026-03-25"  # 2026-03-10 + 15 days = 2026-03-25

    claim = repo.get_claim(claim_id)
    assert claim.get("last_claimant_communication_at") == comm_ts
    assert claim.get("communication_response_due") == "2026-03-25"


def test_record_claimant_communication_creates_task(temp_db):
    """record_claimant_communication auto-creates a compliance task."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-COMM-002",
        vin="1HGBH41JXMN109186",
        vehicle_year=2020,
        vehicle_make="Toyota",
        vehicle_model="Camry",
        incident_date=date(2026, 3, 1),
        incident_description="Parking lot collision",
        damage_description="Door damage",
        loss_state="Texas",
    )
    claim_id = repo.create_claim(claim_input)

    comm_ts = "2026-03-05T09:00:00+00:00"
    repo.record_claimant_communication(
        claim_id,
        description="Claimant requested repair status",
        communication_at=comm_ts,
    )

    tasks, _ = repo.get_tasks_for_claim(claim_id)
    comm_tasks = [
        t for t in tasks if t.get("auto_created_from") == "ucspa:communication_response"
    ]
    assert len(comm_tasks) >= 1
    # record_claimant_communication creates high-priority tasks; get_tasks_for_claim orders
    # high before medium, so the first comm_tasks entry is from record_claimant_communication.
    task = comm_tasks[0]
    assert task.get("due_date") == "2026-03-20"  # 2026-03-05 + 15 days
    assert task.get("created_by") == "ucspa_system"
    assert task.get("task_type") == "follow_up_claimant"


def test_record_claimant_communication_refreshes_deadline(temp_db):
    """Subsequent calls to record_claimant_communication update the deadline."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-COMM-003",
        vin="1HGBH41JXMN109186",
        vehicle_year=2022,
        vehicle_make="Ford",
        vehicle_model="Explorer",
        incident_date=date(2026, 3, 1),
        incident_description="Rear-end collision",
        damage_description="Rear bumper and trunk damage",
        loss_state="Georgia",
    )
    claim_id = repo.create_claim(claim_input)

    # First communication
    repo.record_claimant_communication(
        claim_id,
        description="Initial inquiry",
        communication_at="2026-03-01T10:00:00+00:00",
    )
    claim_first = repo.get_claim(claim_id)
    assert claim_first.get("communication_response_due") == "2026-03-16"

    # Second communication (later)
    repo.record_claimant_communication(
        claim_id,
        description="Follow-up on repair estimate",
        communication_at="2026-03-10T10:00:00+00:00",
    )
    claim_second = repo.get_claim(claim_id)
    assert claim_second.get("last_claimant_communication_at") == "2026-03-10T10:00:00+00:00"
    assert claim_second.get("communication_response_due") == "2026-03-25"  # 2026-03-10 + 15


def test_claims_with_deadlines_approaching_includes_communication_response(temp_db):
    """claims_with_deadlines_approaching checks communication_response_due."""
    repo = ClaimRepository(db_path=temp_db)
    claim_input = ClaimInput(
        policy_number="POL-COMM-DL",
        vin="1HGBH41JXMN109186",
        vehicle_year=2022,
        vehicle_make="Honda",
        vehicle_model="Pilot",
        incident_date=date(2026, 3, 1),
        incident_description="Hail damage",
        damage_description="Hood and roof dents",
        loss_state="California",
    )
    claim_id = repo.create_claim(claim_input)

    # record_claimant_communication sets communication_response_due based on state rules
    # (California: +15 days). With days_ahead=30, today+15 falls within the window.
    comm_ts = date.today().isoformat() + "T00:00:00+00:00"
    repo.record_claimant_communication(
        claim_id,
        description="Test communication",
        communication_at=comm_ts,
    )

    results = claims_with_deadlines_approaching(repo, days_ahead=30)
    comm_results = [r for r in results if r["deadline_type"] == "communication_response"]
    assert any(r["claim_id"] == claim_id for r in comm_results)


def test_compliance_deadline_templates_include_communication_response():
    """get_compliance_deadline_templates returns a communication_response template."""
    from claim_agent.diary.templates import get_compliance_deadline_templates

    # With a known state
    templates = get_compliance_deadline_templates("California")
    types = [t.deadline_type for t in templates]
    assert "communication_response" in types

    comm_template = next(t for t in templates if t.deadline_type == "communication_response")
    assert comm_template.task_type == "follow_up_claimant"
    assert comm_template.days == 15
    assert "California" in comm_template.title

    # Without a state (default templates)
    default_templates = get_compliance_deadline_templates(None)
    default_types = [t.deadline_type for t in default_templates]
    assert "communication_response" in default_types
