"""Tests for denial/coverage dispute tools, logic, and orchestrator."""

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock


from crewai import LLM

os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))


def _load_denial_orchestrator():
    """Load denial_coverage_orchestrator without triggering workflow package circular imports."""
    spec = importlib.util.spec_from_file_location(
        "denial_coverage_orchestrator",
        Path(__file__).resolve().parent.parent / "src" / "claim_agent" / "workflow" / "denial_coverage_orchestrator.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mock_llm():
    """Minimal LLM for structural validation (no API calls)."""
    return LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")


# ---------------------------------------------------------------------------
# Denial logic
# ---------------------------------------------------------------------------


class TestDenialCoverageLogic:
    """Tests for denial_coverage_logic module."""

    def test_generate_denial_letter_impl_minimal(self):
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-001",
            denial_reason="Policy exclusion: pre-existing damage",
            policy_provision="Section 4.2 excludes pre-existing damage",
        )
        assert "CLAIM DENIAL NOTICE" in result
        assert "CLM-001" in result
        assert "Policy exclusion: pre-existing damage" in result
        assert "Section 4.2 excludes pre-existing damage" in result
        assert "Dear Policyholder," in result
        assert "Claims Department" in result

    def test_generate_denial_letter_impl_with_all_fields(self):
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-002",
            denial_reason="Lapsed policy",
            policy_provision="Section 2.1",
            exclusion_citation="Exclusion 3.1",
            appeal_deadline="2025-03-15",
            required_disclosures="California DOI complaint rights",
        )
        assert "EXCLUSION: Exclusion 3.1" in result
        assert "APPEAL RIGHTS:" in result
        assert "2025-03-15" in result
        assert "REQUIRED NOTICES:" in result
        assert "California DOI complaint rights" in result

    def test_route_to_appeal_impl_minimal(self):
        from claim_agent.tools.denial_coverage_logic import route_to_appeal_impl

        result = route_to_appeal_impl(
            claim_id="CLM-001",
            appeal_reason="Exclusion not clearly applicable",
        )
        data = json.loads(result)
        assert data["claim_id"] == "CLM-001"
        assert data["routed_to_appeal"] is True
        assert data["appeal_reason"] == "Exclusion not clearly applicable"
        assert "routed_at" in data

    def test_route_to_appeal_impl_with_optional_fields(self):
        from claim_agent.tools.denial_coverage_logic import route_to_appeal_impl

        result = route_to_appeal_impl(
            claim_id="CLM-002",
            appeal_reason="New evidence",
            policyholder_evidence="Repair estimate from prior shop",
            recommended_action="Review with supervisor",
        )
        data = json.loads(result)
        assert data["policyholder_evidence"] == "Repair estimate from prior shop"
        assert data["recommended_action"] == "Review with supervisor"


# ---------------------------------------------------------------------------
# _parse_outcome
# ---------------------------------------------------------------------------


class TestParseOutcome:
    """Tests for _parse_outcome in denial_coverage_orchestrator."""

    def test_parse_outcome_json_routed_to_appeal(self):
        mod = _load_denial_orchestrator()
        assert mod._parse_outcome('{"routed_to_appeal": true}') == "route_to_appeal"
        assert mod._parse_outcome('{"route_to_appeal": true}') == "route_to_appeal"
        assert mod._parse_outcome('{"routed_to_appeal": "yes"}') == "route_to_appeal"

    def test_parse_outcome_json_outcome_field(self):
        mod = _load_denial_orchestrator()
        assert mod._parse_outcome('{"outcome": "route_to_appeal"}') == "route_to_appeal"
        assert mod._parse_outcome('{"outcome": "escalated"}') == "escalated"
        assert mod._parse_outcome('{"outcome": "uphold_denial"}') == "uphold_denial"
        assert mod._parse_outcome('{"outcome": "escalation required"}') == "escalated"
        assert mod._parse_outcome('{"outcome": "denial upheld"}') == "uphold_denial"

    def test_parse_outcome_heuristic_text(self):
        mod = _load_denial_orchestrator()
        assert mod._parse_outcome("Final determination: route_to_appeal") == "route_to_appeal"
        assert mod._parse_outcome("Routed to appeal") == "route_to_appeal"
        assert mod._parse_outcome("Case escalated for human review") == "escalated"
        assert mod._parse_outcome("Denial upheld. Letter generated.") == "uphold_denial"
        assert mod._parse_outcome("Outcome: uphold denial") == "uphold_denial"

    def test_parse_outcome_ambiguous_defaults_to_escalated(self):
        mod = _load_denial_orchestrator()
        assert mod._parse_outcome("Unclear outcome") == "escalated"
        assert mod._parse_outcome("") == "escalated"
        assert mod._parse_outcome("{}") == "escalated"


# ---------------------------------------------------------------------------
# _build_workflow_output
# ---------------------------------------------------------------------------


class TestBuildWorkflowOutput:
    """Tests for _build_workflow_output in denial_coverage_orchestrator."""

    def test_build_workflow_output_from_tasks_output(self):
        mod = _load_denial_orchestrator()
        task0 = MagicMock()
        task0.output = "Coverage analysis"
        task1 = MagicMock()
        task1.output = "Denial letter content"
        task2 = MagicMock()
        task2.output = "Final determination"
        result = MagicMock()
        result.tasks_output = [task0, task1, task2]
        result.raw = None
        result.output = None

        out = mod._build_workflow_output(result)
        assert "Coverage Analysis:" in out
        assert "Coverage analysis" in out
        assert "Denial Letter / Appeal Note:" in out
        assert "Denial letter content" in out
        assert "Final Determination:" in out
        assert "Final determination" in out

    def test_build_workflow_output_fallback_when_no_tasks_output(self):
        mod = _load_denial_orchestrator()
        result = MagicMock()
        result.tasks_output = None
        result.raw = None
        result.output = "Last task output"

        out = mod._build_workflow_output(result)
        assert out == "Last task output"

    def test_build_workflow_output_fallback_when_fewer_than_three_tasks(self):
        mod = _load_denial_orchestrator()
        result = MagicMock()
        result.tasks_output = [MagicMock(output="Only one task")]
        result.raw = None
        result.output = "Fallback"

        out = mod._build_workflow_output(result)
        assert out == "Fallback"


# ---------------------------------------------------------------------------
# Denial crew structure
# ---------------------------------------------------------------------------


class TestDenialCoverageCrew:
    """Tests for denial coverage crew structure."""

    def test_denial_coverage_crew_has_three_agents(self):
        from claim_agent.crews.denial_coverage_crew import create_denial_coverage_crew

        crew = create_denial_coverage_crew(llm=_mock_llm())
        assert len(crew.agents) == 3
        assert len(crew.tasks) == 3

    def test_denial_coverage_crew_task_inputs(self):
        from claim_agent.crews.denial_coverage_crew import create_denial_coverage_crew

        crew = create_denial_coverage_crew(llm=_mock_llm())
        task_descs = [t.description for t in crew.tasks]
        for desc in task_descs:
            assert "{claim_data}" in desc
            assert "{denial_data}" in desc


# ---------------------------------------------------------------------------
# Orchestrator MidWorkflowEscalation handling
# ---------------------------------------------------------------------------


class TestDenialCoverageOrchestratorEscalation:
    """Tests for orchestrator when crew raises MidWorkflowEscalation."""

    def test_run_denial_coverage_workflow_catches_mid_workflow_escalation(
        self, seeded_temp_db, monkeypatch
    ):
        """When crew raises MidWorkflowEscalation, orchestrator catches and returns outcome=escalated."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.exceptions import MidWorkflowEscalation
        from claim_agent.workflow.denial_coverage_orchestrator import run_denial_coverage_workflow

        repo = ClaimRepository()
        repo.update_claim_status("CLM-TEST001", "denied", details="Test")

        def _kickoff_raises(*args, **kwargs):
            raise MidWorkflowEscalation(
                reason="ambiguous_policy_language",
                indicators=[],
                priority="medium",
                claim_id="CLM-TEST001",
            )

        monkeypatch.setattr(
            "claim_agent.workflow.denial_coverage_orchestrator._kickoff_with_retry",
            _kickoff_raises,
        )

        from claim_agent.context import ClaimContext

        result = run_denial_coverage_workflow(
            {"claim_id": "CLM-TEST001", "denial_reason": "Coverage exclusion"},
            ctx=ClaimContext.from_defaults(),
        )

        assert result["claim_id"] == "CLM-TEST001"
        assert result["outcome"] == "escalated"
        assert result["status"] == "needs_review"
        assert "Escalated" in result["workflow_output"]
        assert "ambiguous_policy_language" in result["summary"]
