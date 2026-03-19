"""Tests for auto-recording settlement payout to claim_payments."""

import tempfile
from pathlib import Path

import pytest

from claim_agent.config import reload_settings
from claim_agent.db.database import init_db
from claim_agent.context import ClaimContext
from claim_agent.db.payment_repository import PaymentRepository
from claim_agent.workflow import orchestrator as orch


@pytest.fixture
def temp_db_wsp():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    try:
        init_db(path)
        yield path
    finally:
        Path(path).unlink(missing_ok=True)


@pytest.fixture
def seeded_db(temp_db_wsp):
    import sqlite3

    conn = sqlite3.connect(temp_db_wsp)
    conn.execute(
        "INSERT INTO claims (id, policy_number, vin, status) VALUES (?, ?, ?, ?)",
        ("CLM-TEST01", "POL-001", "VIN123", "open"),
    )
    conn.commit()
    conn.close()
    return temp_db_wsp


def test_maybe_record_workflow_settlement_payment_creates_row(monkeypatch, seeded_db):
    monkeypatch.setenv("PAYMENT_AUTO_RECORD_FROM_SETTLEMENT", "true")
    reload_settings()

    ctx = ClaimContext.from_defaults(db_path=seeded_db, llm=None)
    wf_ctx = orch._WorkflowCtx(
        claim_id="CLM-TEST01",
        claim_data={},
        claim_data_with_id={
            "claim_id": "CLM-TEST01",
            "parties": [{"party_type": "claimant", "name": "Pat Claimant"}],
        },
        inputs={},
        similarity_score_for_escalation=None,
        context=ctx,
        workflow_run_id="deadbeef",
        workflow_start_time=0.0,
        actor_id="workflow",
        extracted_payout=2500.0,
    )
    orch._maybe_record_workflow_settlement_payment(
        claim_id="CLM-TEST01",
        wf_ctx=wf_ctx,
        workflow_run_id="deadbeef",
        claim_repo=ctx.repo,
    )

    pay_repo = PaymentRepository(db_path=seeded_db)
    rows, total = pay_repo.get_payments_for_claim("CLM-TEST01")
    assert total == 1
    assert rows[0]["amount"] == 2500.0
    assert rows[0]["external_ref"] == "workflow_settlement:deadbeef"
    assert rows[0]["payee"] == "Pat Claimant"

    orch._maybe_record_workflow_settlement_payment(
        claim_id="CLM-TEST01",
        wf_ctx=wf_ctx,
        workflow_run_id="deadbeef",
        claim_repo=ctx.repo,
    )
    _, total2 = pay_repo.get_payments_for_claim("CLM-TEST01")
    assert total2 == 1

    monkeypatch.setenv("PAYMENT_AUTO_RECORD_FROM_SETTLEMENT", "false")
    reload_settings()


def test_maybe_record_skipped_when_disabled(monkeypatch, seeded_db):
    monkeypatch.setenv("PAYMENT_AUTO_RECORD_FROM_SETTLEMENT", "false")
    reload_settings()

    ctx = ClaimContext.from_defaults(db_path=seeded_db, llm=None)
    wf_ctx = orch._WorkflowCtx(
        claim_id="CLM-TEST01",
        claim_data={},
        claim_data_with_id={"claim_id": "CLM-TEST01"},
        inputs={},
        similarity_score_for_escalation=None,
        context=ctx,
        workflow_run_id="run2",
        workflow_start_time=0.0,
        actor_id="workflow",
        extracted_payout=500.0,
    )
    orch._maybe_record_workflow_settlement_payment(
        claim_id="CLM-TEST01",
        wf_ctx=wf_ctx,
        workflow_run_id="run2",
        claim_repo=ctx.repo,
    )
    pay_repo = PaymentRepository(db_path=seeded_db)
    _, total = pay_repo.get_payments_for_claim("CLM-TEST01")
    assert total == 0
