"""Reserve adequacy gate on close/settled transitions (issue #247)."""

import pytest

from claim_agent.config import reload_settings
from claim_agent.db.audit_events import AUDIT_EVENT_RESERVE_ADEQUACY_GATE
from claim_agent.db.constants import STATUS_CLOSED, STATUS_OPEN, STATUS_PROCESSING
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import InvalidClaimTransitionError
from claim_agent.models.claim import ClaimInput


def _claim_input() -> ClaimInput:
    return ClaimInput(
        policy_number="POL-GATE",
        vin="1HGBH41JXMN109888",
        vehicle_year=2020,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date="2024-01-01",
        incident_description="Test",
        damage_description="Dent",
        estimated_damage=10000.0,
    )


def test_block_mode_rejects_close_when_reserve_inadequate(temp_db, monkeypatch):
    monkeypatch.setenv("RESERVE_CLOSE_SETTLE_ADEQUACY_GATE", "block")
    reload_settings()
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_claim_input())
    repo.update_claim_status(cid, STATUS_PROCESSING)
    repo.update_claim_status(cid, STATUS_OPEN)
    repo.adjust_reserve(cid, 1000.0, actor_id="workflow")
    with pytest.raises(InvalidClaimTransitionError, match="Reserve not adequate"):
        repo.update_claim_status(
            cid,
            STATUS_CLOSED,
            payout_amount=5000.0,
            details="Try close",
        )


def test_block_mode_adjuster_cannot_use_skip_flag(temp_db, monkeypatch):
    monkeypatch.setenv("RESERVE_CLOSE_SETTLE_ADEQUACY_GATE", "block")
    reload_settings()
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_claim_input())
    repo.update_claim_status(cid, STATUS_PROCESSING)
    repo.update_claim_status(cid, STATUS_OPEN)
    repo.adjust_reserve(cid, 1000.0, actor_id="workflow")
    with pytest.raises(InvalidClaimTransitionError, match="skip_adequacy_check"):
        repo.update_claim_status(
            cid,
            STATUS_CLOSED,
            payout_amount=5000.0,
            details="Try skip",
            skip_adequacy_check=True,
            role="adjuster",
        )


def test_block_mode_supervisor_skip_allows_close_and_audits_waiver(temp_db, monkeypatch):
    monkeypatch.setenv("RESERVE_CLOSE_SETTLE_ADEQUACY_GATE", "block")
    reload_settings()
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_claim_input())
    repo.update_claim_status(cid, STATUS_PROCESSING)
    repo.update_claim_status(cid, STATUS_OPEN)
    repo.adjust_reserve(cid, 1000.0, actor_id="workflow")
    repo.update_claim_status(
        cid,
        STATUS_CLOSED,
        payout_amount=5000.0,
        details="Closed with waiver",
        skip_adequacy_check=True,
        role="supervisor",
        actor_id="sup-1",
    )
    history, _ = repo.get_claim_history(cid)
    gates = [h for h in history if h.get("action") == AUDIT_EVENT_RESERVE_ADEQUACY_GATE]
    assert len(gates) == 1
    assert "waived" in (gates[0].get("details") or "").lower()


def test_warn_mode_allows_close_and_audits_inadequacy(temp_db, monkeypatch):
    monkeypatch.setenv("RESERVE_CLOSE_SETTLE_ADEQUACY_GATE", "warn")
    reload_settings()
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_claim_input())
    repo.update_claim_status(cid, STATUS_PROCESSING)
    repo.update_claim_status(cid, STATUS_OPEN)
    repo.adjust_reserve(cid, 1000.0, actor_id="workflow")
    repo.update_claim_status(
        cid,
        STATUS_CLOSED,
        payout_amount=5000.0,
        details="Closed despite warn",
    )
    assert repo.get_claim(cid)["status"] == STATUS_CLOSED
    history, _ = repo.get_claim_history(cid)
    gates = [h for h in history if h.get("action") == AUDIT_EVENT_RESERVE_ADEQUACY_GATE]
    assert len(gates) == 1
    assert "warn mode" in (gates[0].get("details") or "").lower()


def test_warn_mode_supervisor_skip_logs_warn_not_waiver(temp_db, monkeypatch):
    """skip_adequacy_check only bypasses block mode; warn mode should not say 'waived'."""
    monkeypatch.setenv("RESERVE_CLOSE_SETTLE_ADEQUACY_GATE", "warn")
    reload_settings()
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_claim_input())
    repo.update_claim_status(cid, STATUS_PROCESSING)
    repo.update_claim_status(cid, STATUS_OPEN)
    repo.adjust_reserve(cid, 1000.0, actor_id="workflow")
    repo.update_claim_status(
        cid,
        STATUS_CLOSED,
        payout_amount=5000.0,
        details="Closed warn + skip flag",
        skip_adequacy_check=True,
        role="supervisor",
        actor_id="sup-1",
    )
    history, _ = repo.get_claim_history(cid)
    gates = [h for h in history if h.get("action") == AUDIT_EVENT_RESERVE_ADEQUACY_GATE]
    assert len(gates) == 1
    d = (gates[0].get("details") or "").lower()
    assert "warn mode" in d
    assert "waived" not in d


def test_off_mode_no_gate_audit_on_inadequate(temp_db, monkeypatch):
    monkeypatch.setenv("RESERVE_CLOSE_SETTLE_ADEQUACY_GATE", "off")
    reload_settings()
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_claim_input())
    repo.update_claim_status(cid, STATUS_PROCESSING)
    repo.update_claim_status(cid, STATUS_OPEN)
    repo.adjust_reserve(cid, 1000.0, actor_id="workflow")
    repo.update_claim_status(
        cid,
        STATUS_CLOSED,
        payout_amount=5000.0,
        details="Closed gate off",
    )
    history, _ = repo.get_claim_history(cid)
    gates = [h for h in history if h.get("action") == AUDIT_EVENT_RESERVE_ADEQUACY_GATE]
    assert len(gates) == 0
