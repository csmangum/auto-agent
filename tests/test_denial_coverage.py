"""Tests for denial/coverage dispute tools, logic, and orchestrator."""

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from crewai import LLM

os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))


def _load_denial_orchestrator():
    """Load denial_coverage_orchestrator without triggering workflow package circular imports."""
    import claim_agent

    pkg_dir = Path(claim_agent.__file__).resolve().parent
    orche_path = pkg_dir / "workflow" / "denial_coverage_orchestrator.py"
    spec = importlib.util.spec_from_file_location("denial_coverage_orchestrator", orche_path)
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

    def test_denial_input_rejects_empty_denial_reason(self):
        """DenialInput enforces min_length=1 when orchestrator is called directly."""
        from pydantic import ValidationError

        from claim_agent.models.denial import DenialInput

        with pytest.raises(ValidationError):
            DenialInput.model_validate(
                {"claim_id": "CLM-001", "denial_reason": ""}
            )

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
        assert "2025-03-15" in result
        assert "California DOI complaint rights" in result

    def test_generate_denial_letter_impl_no_state_generic_format(self):
        """Without state, the generic format is used."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-003",
            denial_reason="No coverage",
            policy_provision="Section 1.0",
        )
        assert "CLAIM DENIAL NOTICE" in result
        # Generic format does not include state-specific header
        assert "CALIFORNIA" not in result
        assert "CCR" not in result

    def test_generate_denial_letter_impl_california(self):
        """California template includes CCR reference and CDI complaint notice."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-CA-001",
            denial_reason="Excluded peril: earthquake",
            policy_provision="Section 3.1 – Excluded Perils",
            state="California",
        )
        assert "CALIFORNIA" in result
        assert "CCR" in result
        assert "2695.7" in result
        assert "California Department of Insurance" in result
        assert "1-800-927-4357" in result
        assert "CLM-CA-001" in result

    def test_generate_denial_letter_impl_california_abbreviation(self):
        """State abbreviation 'CA' resolves to the California template."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-CA-002",
            denial_reason="Policy lapse",
            policy_provision="Section 1.0",
            state="CA",
        )
        assert "CALIFORNIA" in result
        assert "CCR" in result

    def test_generate_denial_letter_impl_texas(self):
        """Texas template includes TIC reference, TDI notice, and 18% penalty disclosure."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-TX-001",
            denial_reason="Policy exclusion: intentional act",
            policy_provision="Section 5.2",
            state="TX",
        )
        assert "TEXAS" in result
        assert "TIC" in result
        assert "Texas Department of Insurance" in result
        assert "18%" in result
        assert "1-800-252-3439" in result

    def test_generate_denial_letter_impl_florida(self):
        """Florida template includes FL statute reference and DFS notice."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-FL-001",
            denial_reason="Coverage lapsed",
            policy_provision="Section 2.0",
            state="FL",
        )
        assert "FLORIDA" in result
        assert "Fla. Stat." in result
        assert "Florida Department of Financial Services" in result
        assert "1-877-693-5236" in result

    def test_generate_denial_letter_impl_new_york(self):
        """New York template includes NY Insurance Law and DFS external appeal notice."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-NY-001",
            denial_reason="Not a covered loss",
            policy_provision="Section 4.1",
            state="NY",
        )
        assert "NEW YORK" in result
        assert "3420" in result
        assert "New York State Department of Financial Services" in result
        assert "external appeal" in result.lower()

    def test_generate_denial_letter_impl_georgia(self):
        """Georgia template includes O.C.G.A reference and OCI notice."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-GA-001",
            denial_reason="Excluded peril",
            policy_provision="Section 3.0",
            state="GA",
        )
        assert "GEORGIA" in result
        assert "O.C.G.A." in result
        assert "Georgia Office of Commissioner of Insurance" in result
        assert "1-800-656-2298" in result

    def test_generate_denial_letter_impl_unsupported_state_falls_back_to_generic(self):
        """Unsupported state falls back to the generic letter format."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-XX-001",
            denial_reason="Not covered",
            policy_provision="Section 1.0",
            state="Alaska",
        )
        # Generic header (no state-specific banner)
        assert "CLAIM DENIAL NOTICE" in result
        assert "ALASKA" not in result

    def test_generate_denial_letter_impl_state_with_appeal_deadline(self):
        """State template with explicit appeal_deadline appends the deadline."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-CA-003",
            denial_reason="No coverage",
            policy_provision="Section 1.0",
            state="California",
            appeal_deadline="2025-06-01",
        )
        assert "2025-06-01" in result
        # State appeal rights block should also appear
        assert "California Department of Insurance" in result

    def test_generate_denial_letter_impl_state_with_extra_disclosures(self):
        """Additional required_disclosures are appended after state disclosures."""
        from claim_agent.tools.denial_coverage_logic import generate_denial_letter_impl

        result = generate_denial_letter_impl(
            claim_id="CLM-TX-002",
            denial_reason="Excluded",
            policy_provision="Section 5.0",
            state="Texas",
            required_disclosures="Please retain this notice for your records.",
        )
        assert "Texas Department of Insurance" in result
        assert "Please retain this notice for your records." in result

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
# Denial templates
# ---------------------------------------------------------------------------


class TestStateDenialTemplates:
    """Tests for the state-specific denial letter template module."""

    def test_get_denial_template_california(self):
        from claim_agent.compliance.denial_templates import get_denial_template

        tpl = get_denial_template("California")
        assert tpl is not None
        assert tpl.state == "California"
        assert tpl.jurisdiction == "CA"
        assert "2695.7" in tpl.regulation_reference

    def test_get_denial_template_abbreviation(self):
        from claim_agent.compliance.denial_templates import get_denial_template

        assert get_denial_template("CA") is not None
        assert get_denial_template("TX") is not None
        assert get_denial_template("FL") is not None
        assert get_denial_template("NY") is not None
        assert get_denial_template("GA") is not None

    def test_get_denial_template_all_five_states(self):
        from claim_agent.compliance.denial_templates import get_denial_template

        for state in ("California", "Florida", "New York", "Texas", "Georgia"):
            tpl = get_denial_template(state)
            assert tpl is not None, f"Template missing for {state}"
            assert tpl.regulation_reference
            assert tpl.appeal_rights_text
            assert tpl.complaint_procedure_text
            assert len(tpl.mandatory_disclosures) > 0

    def test_get_denial_template_unsupported_returns_none(self):
        from claim_agent.compliance.denial_templates import get_denial_template

        assert get_denial_template("Alaska") is None
        assert get_denial_template("") is None
        assert get_denial_template(None) is None

    def test_render_denial_letter_no_state_is_generic(self):
        from claim_agent.compliance.denial_templates import render_denial_letter

        result = render_denial_letter(
            claim_id="CLM-001",
            denial_reason="Not covered",
            policy_provision="Section 1.0",
        )
        assert "CLAIM DENIAL NOTICE" in result
        assert "CLM-001" in result

    def test_render_denial_letter_california_has_ccr(self):
        from claim_agent.compliance.denial_templates import render_denial_letter

        result = render_denial_letter(
            claim_id="CLM-CA-001",
            denial_reason="Excluded peril",
            policy_provision="Section 3.1",
            state="California",
        )
        assert "CCR" in result
        assert "CALIFORNIA" in result
        assert "Claims Department" in result

    def test_render_denial_letter_texas_has_18pct_penalty(self):
        from claim_agent.compliance.denial_templates import render_denial_letter

        result = render_denial_letter(
            claim_id="CLM-TX-001",
            denial_reason="No coverage",
            policy_provision="Section 1.0",
            state="Texas",
        )
        assert "18%" in result

    def test_render_denial_letter_new_york_has_external_appeal(self):
        from claim_agent.compliance.denial_templates import render_denial_letter

        result = render_denial_letter(
            claim_id="CLM-NY-001",
            denial_reason="No coverage",
            policy_provision="Section 1.0",
            state="New York",
        )
        assert "external appeal" in result.lower()

    def test_render_denial_letter_georgia_has_bad_faith_note(self):
        from claim_agent.compliance.denial_templates import render_denial_letter

        result = render_denial_letter(
            claim_id="CLM-GA-001",
            denial_reason="No coverage",
            policy_provision="Section 1.0",
            state="Georgia",
        )
        assert "bad faith" in result.lower() or "§33-4-6" in result

    def test_render_denial_letter_state_appends_explicit_appeal_deadline(self):
        from claim_agent.compliance.denial_templates import render_denial_letter

        result = render_denial_letter(
            claim_id="CLM-CA-002",
            denial_reason="Excluded",
            policy_provision="Sec 2",
            state="California",
            appeal_deadline="2026-01-15",
        )
        assert "APPEAL DEADLINE" in result
        assert "2026-01-15" in result



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
        from claim_agent.context import ClaimContext
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.exceptions import MidWorkflowEscalation

        mod = _load_denial_orchestrator()

        repo = ClaimRepository()
        repo.update_claim_status("CLM-TEST001", "denied", details="Test")

        def _kickoff_raises(*args, **kwargs):
            raise MidWorkflowEscalation(
                reason="ambiguous_policy_language",
                indicators=[],
                priority="medium",
                claim_id="CLM-TEST001",
            )

        monkeypatch.setattr(mod, "_kickoff_with_retry", _kickoff_raises)

        result = mod.run_denial_coverage_workflow(
            {"claim_id": "CLM-TEST001", "denial_reason": "Coverage exclusion"},
            llm=_mock_llm(),
            ctx=ClaimContext.from_defaults(),
        )

        assert result["claim_id"] == "CLM-TEST001"
        assert result["outcome"] == "escalated"
        assert result["status"] == "needs_review"
        assert "Escalated" in result["workflow_output"]
        assert "ambiguous_policy_language" in result["summary"]
