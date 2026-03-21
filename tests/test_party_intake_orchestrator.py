"""Tests for party intake workflow orchestrator."""

import os
import tempfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from claim_agent.context import ClaimContext
from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.claim import ClaimInput
from claim_agent.workflow.party_intake_orchestrator import run_party_intake_workflow


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    prev = os.environ.get("CLAIMS_DB_PATH")
    os.environ["CLAIMS_DB_PATH"] = path
    try:
        yield path
    finally:
        if prev is None:
            os.environ.pop("CLAIMS_DB_PATH", None)
        else:
            os.environ["CLAIMS_DB_PATH"] = prev
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture
def claim_id(temp_db):
    repo = ClaimRepository(db_path=temp_db)
    return repo.create_claim(
        ClaimInput(
            policy_number="POL-123",
            vin="1VIN",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date=date(2025, 1, 15),
            incident_description="Collision",
            damage_description="Front",
        )
    )


def test_party_intake_raises_for_missing_claim(temp_db):
    mock_llm = MagicMock()
    ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)
    with pytest.raises(ClaimNotFoundError):
        run_party_intake_workflow("CLM-NONE", "Witness: Jane", llm=mock_llm, ctx=ctx)


def test_party_intake_runs_with_stubbed_crew(claim_id, temp_db, monkeypatch):
    mock_result = MagicMock()
    mock_result.raw = "Witness and attorney intake complete."

    monkeypatch.setattr(
        "claim_agent.workflow.party_intake_orchestrator.create_party_intake_crew",
        lambda **kw: MagicMock(),
    )
    monkeypatch.setattr(
        "claim_agent.workflow.party_intake_orchestrator._kickoff_with_retry",
        lambda crew, inputs: mock_result,
    )

    mock_llm = MagicMock()
    ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)
    out = run_party_intake_workflow(
        claim_id,
        "Record witness Jane; attorney LOP on file.",
        llm=mock_llm,
        ctx=ctx,
    )
    assert out["claim_id"] == claim_id
    assert "Witness" in out["workflow_output"]
