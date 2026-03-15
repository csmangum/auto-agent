"""Tests for the SIU investigation workflow orchestrator."""

import os
import tempfile
from unittest.mock import MagicMock

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import ClaimNotFoundError
from claim_agent.models.claim import ClaimInput
from claim_agent.workflow.siu_orchestrator import run_siu_investigation


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
def claim_under_investigation(repo):
    """Claim with status under_investigation and no siu_case_id."""
    inp = ClaimInput(
        policy_number="POL-SIU",
        vin="1HGBH41JXMN109186",
        vehicle_year=2021,
        vehicle_make="Honda",
        vehicle_model="Accord",
        incident_date="2025-01-15",
        incident_description="Suspicious claim",
        damage_description="Bumper damage",
    )
    claim_id = repo.create_claim(inp)
    repo.update_claim_status(claim_id, "needs_review", actor_id="workflow")
    repo.escalate_claim_to_siu(claim_id, actor_id="adjuster")
    return claim_id


@pytest.fixture
def claim_fraud_suspected(repo):
    """Claim with status fraud_suspected."""
    inp = ClaimInput(
        policy_number="POL-FRAUD",
        vin="5YJSA1E26HF123456",
        vehicle_year=2020,
        vehicle_make="Tesla",
        vehicle_model="Model 3",
        incident_date="2025-01-20",
        incident_description="Staged accident",
        damage_description="Total loss",
    )
    claim_id = repo.create_claim(inp)
    repo.update_claim_status(claim_id, "fraud_suspected", actor_id="fraud_crew")
    return claim_id


class TestRunSiuInvestigation:
    """Tests for run_siu_investigation."""

    def test_raises_for_unknown_claim(self, temp_db):
        """run_siu_investigation raises ClaimNotFoundError for a missing claim."""
        from claim_agent.context import ClaimContext

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        with pytest.raises(ClaimNotFoundError):
            run_siu_investigation("CLM-NONEXISTENT", llm=mock_llm, ctx=ctx)

    def test_raises_for_invalid_status(self, repo, temp_db):
        """run_siu_investigation raises ValueError when claim status is not eligible."""
        from claim_agent.context import ClaimContext

        inp = ClaimInput(
            policy_number="POL-OPEN",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-01-15",
            incident_description="Open claim",
            damage_description="Minor",
        )
        claim_id = repo.create_claim(inp)

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        with pytest.raises(ValueError, match="requires status"):
            run_siu_investigation(claim_id, llm=mock_llm, ctx=ctx)

    def test_creates_siu_case_when_missing(self, claim_under_investigation, temp_db, monkeypatch):
        """When claim has no siu_case_id, orchestrator creates case and persists it."""
        from claim_agent.context import ClaimContext

        mock_result = MagicMock()
        mock_result.raw = "Document verification complete. Records check done. Case closed."

        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator.create_siu_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator._kickoff_with_retry",
            lambda crew, inputs: mock_result,
        )

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        result = run_siu_investigation(
            claim_under_investigation,
            llm=mock_llm,
            ctx=ctx,
        )

        assert result["claim_id"] == claim_under_investigation
        assert "workflow_output" in result
        assert "summary" in result

        claim = ctx.repo.get_claim(claim_under_investigation)
        assert claim["siu_case_id"] is not None
        assert claim["siu_case_id"].startswith("SIU-MOCK-")

    def test_runs_with_existing_siu_case(self, claim_fraud_suspected, temp_db, monkeypatch):
        """Orchestrator runs when claim already has siu_case_id (e.g. from fraud workflow)."""
        from claim_agent.context import ClaimContext

        repo = ClaimRepository(db_path=temp_db)
        case_id = "SIU-MOCK-EXISTING"
        repo.update_claim_siu_case_id(claim_fraud_suspected, case_id, actor_id="fraud_crew")

        mock_result = MagicMock()
        mock_result.raw = "Investigation complete."

        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator.create_siu_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator._kickoff_with_retry",
            lambda crew, inputs: mock_result,
        )

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        result = run_siu_investigation(
            claim_fraud_suspected,
            llm=mock_llm,
            ctx=ctx,
        )

        assert result["claim_id"] == claim_fraud_suspected
        assert "Investigation complete." in result["workflow_output"]

    def test_passes_claim_data_to_crew(self, claim_under_investigation, temp_db, monkeypatch):
        """Crew inputs include claim_data with siu_case_id, vin, policy_number."""
        captured_inputs = {}

        def fake_kickoff(crew, inputs):
            captured_inputs.update(inputs)
            mock_result = MagicMock()
            mock_result.raw = "Done"
            return mock_result

        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator.create_siu_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator._kickoff_with_retry",
            fake_kickoff,
        )

        from claim_agent.context import ClaimContext

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        run_siu_investigation(claim_under_investigation, llm=mock_llm, ctx=ctx)

        assert "claim_data" in captured_inputs
        import json

        claim_data = json.loads(captured_inputs["claim_data"])
        assert claim_data["id"] == claim_under_investigation
        assert claim_data["siu_case_id"]
        assert claim_data["vin"]
        assert claim_data["policy_number"]
        assert claim_data["status"] == "under_investigation"
        assert claim_data["state"] == "California"

    def test_derives_state_from_policy_when_available(self, claim_under_investigation, temp_db, monkeypatch):
        """claim_data state is derived from policy when policy has state."""
        import json

        captured_inputs = {}

        def fake_kickoff(crew, inputs):
            captured_inputs.update(inputs)
            mock_result = MagicMock()
            mock_result.raw = "Done"
            return mock_result

        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator.create_siu_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator._kickoff_with_retry",
            fake_kickoff,
        )

        from claim_agent.context import ClaimContext

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)
        original_get_policy = ctx.adapters.policy.get_policy

        def policy_with_state(policy_number):
            result = original_get_policy(policy_number)
            if policy_number == "POL-SIU":
                base = result or {"status": "active", "coverages": []}
                return {**base, "state": "Texas"}
            return result

        monkeypatch.setattr(ctx.adapters.policy, "get_policy", policy_with_state)

        run_siu_investigation(claim_under_investigation, llm=mock_llm, ctx=ctx)

        claim_data = json.loads(captured_inputs["claim_data"])
        assert claim_data["state"] == "Texas"

    def test_adds_failure_note_when_crew_raises(
        self, claim_under_investigation, temp_db, monkeypatch
    ):
        """When crew kickoff raises, orchestrator adds failure note to SIU case and claim."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.context import ClaimContext

        def raise_crew_failed(crew, inputs):
            raise RuntimeError("Crew failed")

        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator.create_siu_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator._kickoff_with_retry",
            raise_crew_failed,
        )

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        with pytest.raises(RuntimeError, match="Crew failed"):
            run_siu_investigation(
                claim_under_investigation,
                llm=mock_llm,
                ctx=ctx,
            )

        claim = ctx.repo.get_claim(claim_under_investigation)
        case_id = claim["siu_case_id"]
        assert case_id is not None

        adapter = get_siu_adapter()
        case = adapter.get_case(case_id)
        assert case is not None
        notes = [n for n in case.get("notes", []) if "SIU workflow failed" in n.get("note", "")]
        assert len(notes) == 1
        assert "Crew failed" in notes[0]["note"]

        claim_notes = ctx.repo.get_notes(claim_under_investigation)
        failure_notes = [n for n in claim_notes if "SIU workflow failed" in n.get("note", "")]
        assert len(failure_notes) == 1
        assert "Crew failed" in failure_notes[0]["note"]

    def test_returns_structured_output_when_case_manager_produces_pydantic(
        self, claim_under_investigation, temp_db, monkeypatch
    ):
        """When Case Manager produces SIUInvestigationResult, response includes structured fields."""
        from claim_agent.context import ClaimContext
        from claim_agent.models.workflow_output import SIUInvestigationResult

        structured = SIUInvestigationResult(
            findings_summary="Documents verified. No prior fraud.",
            recommendation="closed_no_fraud",
            case_status="closed",
            state_report_filed=False,
            documents_verified=[{"type": "proof_of_loss", "verified": True}],
            prior_claims_summary="No prior claims on VIN.",
            tool_failures_noted=None,
        )

        mock_task = MagicMock()
        mock_task.pydantic = structured
        mock_task.output = structured

        mock_result = MagicMock()
        mock_result.raw = "Investigation complete."
        mock_result.tasks_output = [MagicMock(), MagicMock(), mock_task]

        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator.create_siu_crew",
            lambda **kw: MagicMock(),
        )
        monkeypatch.setattr(
            "claim_agent.workflow.siu_orchestrator._kickoff_with_retry",
            lambda crew, inputs: mock_result,
        )

        mock_llm = MagicMock()
        ctx = ClaimContext.from_defaults(db_path=temp_db, llm=mock_llm)

        result = run_siu_investigation(
            claim_under_investigation,
            llm=mock_llm,
            ctx=ctx,
        )

        assert result["claim_id"] == claim_under_investigation
        assert result["siu_case_id"] is not None
        assert result["findings_summary"] == "Documents verified. No prior fraud."
        assert result["recommendation"] == "closed_no_fraud"
        assert result["case_status"] == "closed"
        assert result["state_report_filed"] is False
        assert len(result["documents_verified"]) == 1
        assert result["documents_verified"][0]["type"] == "proof_of_loss"
        assert result["prior_claims_summary"] == "No prior claims on VIN."
        assert result["tool_failures_noted"] is None
