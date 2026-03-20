"""Reserve adequacy gate on close/settled transitions (issue #247)."""

import pytest

from claim_agent.config import reload_settings
from claim_agent.db.audit_events import AUDIT_EVENT_RESERVE_ADEQUACY_GATE
from claim_agent.db.constants import (
    STATUS_CLOSED,
    STATUS_OPEN,
    STATUS_PROCESSING,
    STATUS_SETTLED,
)
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


def _repo_partial_loss_open_ready(temp_db) -> tuple[ClaimRepository, str]:
    """Claim on open with partial_loss and repair_ready_for_settlement=True, low reserve."""
    repo = ClaimRepository(db_path=temp_db)
    cid = repo.create_claim(_claim_input())
    repo.update_claim_status(cid, STATUS_PROCESSING)
    repo.update_claim_status(cid, STATUS_OPEN, details="open", claim_type="partial_loss")
    repo.update_claim_status(
        cid,
        STATUS_OPEN,
        details="ready",
        claim_type="partial_loss",
        repair_ready_for_settlement=True,
    )
    repo.adjust_reserve(cid, 1000.0, actor_id="workflow")
    return repo, cid


def test_skip_validation_bypasses_reserve_gate_in_block_mode_no_gate_audit(
    temp_db, monkeypatch
):
    """skip_validation skips validate_transition; block-mode gate does not run or audit."""
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
        details="Bypass via skip_validation",
        skip_validation=True,
    )
    assert repo.get_claim(cid)["status"] == STATUS_CLOSED
    history, _ = repo.get_claim_history(cid)
    gates = [h for h in history if h.get("action") == AUDIT_EVENT_RESERVE_ADEQUACY_GATE]
    assert len(gates) == 0


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


def test_block_mode_rejects_settle_when_reserve_inadequate(temp_db, monkeypatch):
    monkeypatch.setenv("RESERVE_CLOSE_SETTLE_ADEQUACY_GATE", "block")
    reload_settings()
    repo, cid = _repo_partial_loss_open_ready(temp_db)
    with pytest.raises(InvalidClaimTransitionError, match="Reserve not adequate"):
        repo.update_claim_status(
            cid,
            STATUS_SETTLED,
            payout_amount=5000.0,
            details="Try settle",
        )


def test_warn_mode_allows_settle_and_audits_inadequacy(temp_db, monkeypatch):
    monkeypatch.setenv("RESERVE_CLOSE_SETTLE_ADEQUACY_GATE", "warn")
    reload_settings()
    repo, cid = _repo_partial_loss_open_ready(temp_db)
    repo.update_claim_status(
        cid,
        STATUS_SETTLED,
        payout_amount=5000.0,
        details="Settled despite warn",
    )
    assert repo.get_claim(cid)["status"] == STATUS_SETTLED
    history, _ = repo.get_claim_history(cid)
    gates = [h for h in history if h.get("action") == AUDIT_EVENT_RESERVE_ADEQUACY_GATE]
    assert len(gates) == 1
    assert "warn mode" in (gates[0].get("details") or "").lower()


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


def test_block_mode_executive_skip_allows_close_and_audits_waiver(temp_db, monkeypatch):
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
        details="Closed executive waiver",
        skip_adequacy_check=True,
        role="executive",
        actor_id="exec-1",
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
