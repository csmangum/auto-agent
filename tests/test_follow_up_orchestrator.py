"""Tests for the follow-up workflow orchestrator."""

import os
import tempfile
from datetime import date
from unittest.mock import MagicMock

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.claim import ClaimInput
from claim_agent.workflow.follow_up_orchestrator import run_follow_up_workflow


@pytest.fixture
def temp_db():
    """Temp DB with CLAIMS_DB_PATH set."""
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
def repo(temp_db):
    return ClaimRepository(db_path=temp_db)


@pytest.fixture
def claim_id(repo):
    inp = ClaimInput(
        policy_number="POL-123",
        vin="1HGBH41JXMN109186",
        vehicle_year=2021,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date=date(2025, 1, 15),
        incident_description="Rear-end collision",
        damage_description="Bumper damage",
    )
    return repo.create_claim(inp)


class TestRunFollowUpWorkflow:
    """Tests for run_follow_up_workflow."""

    def test_raises_for_unknown_claim(self, temp_db):
        """run_follow_up_workflow raises ClaimNotFoundError for a missing claim."""
        from claim_agent.context import ClaimContext

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        with pytest.raises(ClaimNotFoundError):
            run_follow_up_workflow(
                "CLM-NONEXISTENT",
                "Gather photos from claimant",
                llm=mock_llm,
                ctx=ctx,
            )

    def test_runs_without_template_errors(self, claim_id, temp_db, monkeypatch):
        """run_follow_up_workflow completes without KeyError from missing template inputs."""
        from claim_agent.context import ClaimContext

        # Stub crew kickoff to avoid real LLM calls
        mock_result = MagicMock()
        mock_result.raw = "Follow-up message sent to claimant."

        monkeypatch.setattr(
            "claim_agent.workflow.follow_up_orchestrator.create_follow_up_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.follow_up_orchestrator._kickoff_with_retry",
            lambda crew, inputs: mock_result,
        )

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        result = run_follow_up_workflow(
            claim_id,
            "Gather photos of damage from claimant",
            llm=mock_llm,
            ctx=ctx,
        )

        assert result["claim_id"] == claim_id
        assert "workflow_output" in result
        assert "summary" in result
        assert "Follow-up" in result["workflow_output"]

    def test_passes_user_response_in_inputs(self, claim_id, temp_db, monkeypatch):
        """user_response is forwarded to crew inputs when provided."""
        captured_inputs = {}

        def fake_kickoff(crew, inputs):
            captured_inputs.update(inputs)
            mock_result = MagicMock()
            mock_result.raw = "Processed user response."
            return mock_result

        monkeypatch.setattr(
            "claim_agent.workflow.follow_up_orchestrator.create_follow_up_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.follow_up_orchestrator._kickoff_with_retry",
            fake_kickoff,
        )
        mock_llm = MagicMock()
        monkeypatch.setattr(
            "claim_agent.workflow.follow_up_orchestrator.get_llm",
            lambda: mock_llm,
        )

        from claim_agent.context import ClaimContext

        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=None)

        run_follow_up_workflow(
            claim_id,
            "Ask for more info",
            ctx=ctx,
            user_response="I uploaded the photos.",
        )

        assert captured_inputs.get("user_response") == "I uploaded the photos."
        assert "claim_data" in captured_inputs
        assert "task" in captured_inputs
        assert "claim_notes" in captured_inputs

    def test_default_user_response_placeholder(self, claim_id, temp_db, monkeypatch):
        """When user_response is None the default placeholder string is used."""
        captured_inputs = {}

        def fake_kickoff(crew, inputs):
            captured_inputs.update(inputs)
            mock_result = MagicMock()
            mock_result.raw = "done"
            return mock_result

        monkeypatch.setattr(
            "claim_agent.workflow.follow_up_orchestrator.create_follow_up_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.follow_up_orchestrator._kickoff_with_retry",
            fake_kickoff,
        )
        mock_llm = MagicMock()
        monkeypatch.setattr(
            "claim_agent.workflow.follow_up_orchestrator.get_llm",
            lambda: mock_llm,
        )

        from claim_agent.context import ClaimContext

        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=None)

        run_follow_up_workflow(claim_id, "Check in", ctx=ctx)

        assert captured_inputs.get("user_response") == "No response provided yet."
