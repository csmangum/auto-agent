"""Tests for the policyholder dispute crew, tools, and orchestrator."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from crewai import LLM

os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestDisputeModels:
    def test_dispute_type_values(self):
        from claim_agent.models.dispute import DisputeType

        assert DisputeType.LIABILITY_DETERMINATION.value == "liability_determination"
        assert DisputeType.VALUATION_DISAGREEMENT.value == "valuation_disagreement"
        assert DisputeType.REPAIR_ESTIMATE.value == "repair_estimate"
        assert DisputeType.DEDUCTIBLE_APPLICATION.value == "deductible_application"

    def test_auto_resolvable_set(self):
        from claim_agent.models.dispute import AUTO_RESOLVABLE_DISPUTE_TYPES, DisputeType

        assert DisputeType.VALUATION_DISAGREEMENT in AUTO_RESOLVABLE_DISPUTE_TYPES
        assert DisputeType.REPAIR_ESTIMATE in AUTO_RESOLVABLE_DISPUTE_TYPES
        assert DisputeType.DEDUCTIBLE_APPLICATION in AUTO_RESOLVABLE_DISPUTE_TYPES
        assert DisputeType.LIABILITY_DETERMINATION not in AUTO_RESOLVABLE_DISPUTE_TYPES

    def test_dispute_input_validation(self):
        from claim_agent.models.dispute import DisputeInput

        inp = DisputeInput(
            claim_id="CLM-001",
            dispute_type="valuation_disagreement",
            dispute_description="ACV is too low",
        )
        assert inp.claim_id == "CLM-001"
        assert inp.dispute_type.value == "valuation_disagreement"
        assert inp.policyholder_evidence is None

    def test_dispute_input_with_evidence(self):
        from claim_agent.models.dispute import DisputeInput

        inp = DisputeInput(
            claim_id="CLM-002",
            dispute_type="repair_estimate",
            dispute_description="OEM parts required",
            policyholder_evidence="Policy section 4.2 mandates OEM parts",
        )
        assert inp.policyholder_evidence is not None

    def test_dispute_input_invalid_type(self):
        from claim_agent.models.dispute import DisputeInput

        with pytest.raises(Exception):
            DisputeInput(
                claim_id="CLM-003",
                dispute_type="invalid_type",
                dispute_description="Test",
            )

    def test_dispute_output_model(self):
        from claim_agent.models.dispute import DisputeOutput

        out = DisputeOutput(
            claim_id="CLM-001",
            dispute_type="valuation_disagreement",
            resolution_type="auto_resolved",
            findings="ACV recalculated and adjusted",
            adjusted_amount=15500.0,
            original_amount=14000.0,
            recommended_action="Pay adjusted amount",
            compliance_notes=["DISC-005: Appraisal rights disclosed"],
        )
        assert out.resolution_type == "auto_resolved"
        assert out.adjusted_amount == 15500.0


# ---------------------------------------------------------------------------
# Dispute logic (tools)
# ---------------------------------------------------------------------------


class TestDisputeLogic:
    def test_classify_dispute_with_hint(self):
        from claim_agent.tools.dispute_logic import classify_dispute_impl

        result = json.loads(classify_dispute_impl(
            {"payout_amount": 14000},
            "I think the valuation is wrong",
            "valuation_disagreement",
        ))
        assert result["dispute_type"] == "valuation_disagreement"
        assert result["auto_resolvable"] is True

    def test_classify_dispute_by_keywords_valuation(self):
        from claim_agent.tools.dispute_logic import classify_dispute_impl

        result = json.loads(classify_dispute_impl(
            {},
            "The actual cash value and comparable vehicles used are inaccurate",
        ))
        assert result["dispute_type"] == "valuation_disagreement"
        assert result["auto_resolvable"] is True

    def test_classify_dispute_by_keywords_repair(self):
        from claim_agent.tools.dispute_logic import classify_dispute_impl

        result = json.loads(classify_dispute_impl(
            {},
            "Policy requires OEM parts not aftermarket",
        ))
        assert result["dispute_type"] == "repair_estimate"

    def test_classify_dispute_by_keywords_deductible(self):
        from claim_agent.tools.dispute_logic import classify_dispute_impl

        result = json.loads(classify_dispute_impl(
            {},
            "Wrong deductible amount was applied to my claim",
        ))
        assert result["dispute_type"] == "deductible_application"

    def test_classify_dispute_by_keywords_liability(self):
        from claim_agent.tools.dispute_logic import classify_dispute_impl

        result = json.loads(classify_dispute_impl(
            {},
            "The other driver was at fault, not me. Witness confirms.",
        ))
        assert result["dispute_type"] == "liability_determination"
        assert result["auto_resolvable"] is False

    def test_classify_dispute_unknown_defaults_to_liability(self):
        from claim_agent.tools.dispute_logic import classify_dispute_impl

        result = json.loads(classify_dispute_impl(
            {},
            "I disagree with everything",
        ))
        assert result["dispute_type"] == "liability_determination"
        assert result["auto_resolvable"] is False

    def test_lookup_original_claim_not_found(self):
        from claim_agent.tools.dispute_logic import lookup_original_claim_impl

        result = json.loads(lookup_original_claim_impl("CLM-NONEXISTENT"))
        assert "error" in result

    def test_lookup_original_claim_found(self, seeded_temp_db):
        from claim_agent.tools.dispute_logic import lookup_original_claim_impl

        result = json.loads(lookup_original_claim_impl("CLM-TEST001"))
        assert result["claim_id"] == "CLM-TEST001"
        assert result["claim"]["status"] == "open"
        assert result["claim"]["policy_number"] == "POL-001"
        assert isinstance(result["workflow_runs"], list)
        assert len(result["workflow_runs"]) >= 1

    def test_generate_dispute_report_auto_resolved(self):
        from claim_agent.tools.dispute_logic import generate_dispute_report_impl

        report = generate_dispute_report_impl(
            claim_id="CLM-001",
            dispute_type="valuation_disagreement",
            resolution_type="auto_resolved",
            findings="ACV recalculated to $15,500",
            original_amount="14000",
            adjusted_amount="15500",
            compliance_notes=["DISC-005: Appraisal rights disclosed"],
        )
        assert "DISPUTE RESOLUTION REPORT" in report
        assert "AUTO RESOLVED" in report
        assert "Valuation Disagreement" in report
        assert "$14,000.00" in report
        assert "$15,500.00" in report
        assert "DISC-005" in report

    def test_generate_dispute_report_escalated(self):
        from claim_agent.tools.dispute_logic import generate_dispute_report_impl

        report = generate_dispute_report_impl(
            claim_id="CLM-002",
            dispute_type="liability_determination",
            resolution_type="escalated",
            findings="Liability disputed, witness statements conflict",
            escalation_reasons=["Conflicting witness accounts", "No police report"],
            recommended_action="Assign senior adjuster for investigation",
            policyholder_rights=["Right to arbitration per CIC 11580.2(f)"],
        )
        assert "ESCALATED" in report
        assert "Conflicting witness accounts" in report
        assert "arbitration" in report


# ---------------------------------------------------------------------------
# Dispute tools (CrewAI wrappers)
# ---------------------------------------------------------------------------


class TestDisputeTools:
    def test_lookup_original_claim_tool(self, seeded_temp_db):
        from claim_agent.tools.dispute_tools import lookup_original_claim

        result = lookup_original_claim.run(claim_id="CLM-TEST001")
        data = json.loads(result)
        assert data["claim_id"] == "CLM-TEST001"

    def test_classify_dispute_tool(self):
        from claim_agent.tools.dispute_tools import classify_dispute

        result = classify_dispute.run(
            claim_data='{"payout_amount": 14000}',
            dispute_description="ACV is too low",
            dispute_type_hint="valuation_disagreement",
        )
        data = json.loads(result)
        assert data["dispute_type"] == "valuation_disagreement"

    def test_generate_dispute_report_tool(self):
        from claim_agent.tools.dispute_tools import generate_dispute_report

        result = generate_dispute_report.run(
            claim_id="CLM-001",
            dispute_type="valuation_disagreement",
            resolution_type="auto_resolved",
            findings="Recalculated ACV",
        )
        assert "DISPUTE RESOLUTION REPORT" in result


# ---------------------------------------------------------------------------
# Tools __init__ lazy loading
# ---------------------------------------------------------------------------


class TestToolsInit:
    def test_dispute_tools_importable(self):
        from claim_agent.tools import (
            classify_dispute,
            generate_dispute_report,
            lookup_original_claim,
        )

        assert callable(lookup_original_claim.run)
        assert callable(classify_dispute.run)
        assert callable(generate_dispute_report.run)


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------


class TestDisputeSkills:
    def test_skill_constants_exist(self):
        from claim_agent.skills import (
            DISPUTE_INTAKE,
            DISPUTE_POLICY_ANALYST,
            DISPUTE_RESOLUTION,
        )

        assert DISPUTE_INTAKE == "dispute_intake"
        assert DISPUTE_POLICY_ANALYST == "dispute_policy_analyst"
        assert DISPUTE_RESOLUTION == "dispute_resolution"

    def test_skill_files_loadable(self):
        from claim_agent.skills import (
            DISPUTE_INTAKE,
            DISPUTE_POLICY_ANALYST,
            DISPUTE_RESOLUTION,
            load_skill,
        )

        for skill_name in (DISPUTE_INTAKE, DISPUTE_POLICY_ANALYST, DISPUTE_RESOLUTION):
            skill = load_skill(skill_name)
            assert skill["role"], f"Skill {skill_name} missing role"
            assert skill["goal"], f"Skill {skill_name} missing goal"
            assert skill["backstory"], f"Skill {skill_name} missing backstory"


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------


class TestDisputeAgents:
    def test_create_dispute_intake_agent(self):
        from claim_agent.agents.dispute import create_dispute_intake_agent

        mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-test")
        agent = create_dispute_intake_agent(llm=mock_llm)
        assert agent.role
        tool_names = [getattr(t, "name", str(t)) for t in (agent.tools or [])]
        assert any("lookup" in n.lower() or "original" in n.lower() for n in tool_names)
        assert any("classify" in n.lower() or "dispute" in n.lower() for n in tool_names)

    def test_create_dispute_policy_analyst_agent(self):
        from claim_agent.agents.dispute import create_dispute_policy_analyst_agent

        mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-test")
        agent = create_dispute_policy_analyst_agent(llm=mock_llm)
        assert agent.role
        tool_names = [getattr(t, "name", str(t)) for t in (agent.tools or [])]
        assert any("compliance" in n.lower() or "policy" in n.lower() for n in tool_names)

    def test_create_dispute_resolution_agent(self):
        from claim_agent.agents.dispute import create_dispute_resolution_agent

        mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-test")
        agent = create_dispute_resolution_agent(llm=mock_llm)
        assert agent.role
        tool_names = [getattr(t, "name", str(t)) for t in (agent.tools or [])]
        assert any("dispute" in n.lower() and "report" in n.lower() for n in tool_names)
        assert any("escalate" in n.lower() for n in tool_names)


# ---------------------------------------------------------------------------
# Crew structure
# ---------------------------------------------------------------------------


class TestDisputeCrew:
    def test_dispute_crew_structure(self):
        from claim_agent.crews.dispute_crew import create_dispute_crew

        mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-test")
        crew = create_dispute_crew(llm=mock_llm)

        assert len(crew.agents) == 3
        assert len(crew.tasks) == 3

        intake_task, policy_task, resolution_task = crew.tasks

        assert "{claim_data}" in intake_task.description
        assert "{dispute_data}" in intake_task.description
        assert "lookup_original_claim" in intake_task.description
        assert "classify_dispute" in intake_task.description

        assert intake_task in policy_task.context
        assert "query_policy_db" in policy_task.description
        assert "compliance" in policy_task.description.lower()

        assert intake_task in resolution_task.context
        assert policy_task in resolution_task.context
        assert "auto-resolvable" in resolution_task.description.lower() or "auto_resolvable" in resolution_task.description.lower()
        assert "escalation" in resolution_task.description.lower()

    def test_dispute_crew_task_inputs(self):
        from claim_agent.crews.dispute_crew import create_dispute_crew

        mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-test")
        crew = create_dispute_crew(llm=mock_llm)

        resolution_task = crew.tasks[2]
        assert "{original_workflow_output}" in resolution_task.description


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


class TestDisputeOrchestrator:
    def test_infer_resolution_type_auto_resolved(self):
        from claim_agent.workflow.dispute_orchestrator import _infer_resolution_type
        from claim_agent.models.dispute import DisputeType

        assert _infer_resolution_type(
            "Resolution: AUTO_RESOLVED", DisputeType.VALUATION_DISAGREEMENT
        ) == "auto_resolved"

    def test_infer_resolution_type_escalated(self):
        from claim_agent.workflow.dispute_orchestrator import _infer_resolution_type
        from claim_agent.models.dispute import DisputeType

        assert _infer_resolution_type(
            "Claim has been escalated for human review", DisputeType.LIABILITY_DETERMINATION
        ) == "escalated"

    def test_infer_resolution_type_fallback_auto(self):
        from claim_agent.workflow.dispute_orchestrator import _infer_resolution_type
        from claim_agent.models.dispute import DisputeType

        assert _infer_resolution_type(
            "No clear keywords here", DisputeType.DEDUCTIBLE_APPLICATION
        ) == "auto_resolved"

    def test_infer_resolution_type_fallback_escalate(self):
        from claim_agent.workflow.dispute_orchestrator import _infer_resolution_type
        from claim_agent.models.dispute import DisputeType

        assert _infer_resolution_type(
            "No clear keywords here", DisputeType.LIABILITY_DETERMINATION
        ) == "escalated"

    def test_extract_adjusted_amount(self):
        from claim_agent.workflow.dispute_orchestrator import _extract_adjusted_amount

        assert _extract_adjusted_amount("Adjusted Amount: $15,500.00") == 15500.0
        assert _extract_adjusted_amount("new amount: $12000") == 12000.0
        assert _extract_adjusted_amount("revised payout: $8,250.50") == 8250.50
        assert _extract_adjusted_amount("No adjustment needed") is None

    def test_run_dispute_workflow_claim_not_found(self):
        from claim_agent.exceptions import ClaimNotFoundError
        from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow

        with pytest.raises(ClaimNotFoundError):
            run_dispute_workflow({
                "claim_id": "CLM-NONEXISTENT",
                "dispute_type": "valuation_disagreement",
                "dispute_description": "ACV too low",
            })

    def test_run_dispute_workflow_auto_resolve(self, seeded_temp_db):
        from claim_agent.db.constants import STATUS_DISPUTE_RESOLVED
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow

        mock_result = MagicMock()
        mock_result.raw = "Resolution: AUTO_RESOLVED. Adjusted amount: $16,000.00. Findings: ACV recalculated."

        with patch("claim_agent.workflow.dispute_orchestrator.create_dispute_crew") as mock_crew_fn:
            mock_crew = MagicMock()
            mock_crew.kickoff.return_value = mock_result
            mock_crew_fn.return_value = mock_crew

            result = run_dispute_workflow({
                "claim_id": "CLM-TEST001",
                "dispute_type": "valuation_disagreement",
                "dispute_description": "ACV is too low",
            })

        assert result["claim_id"] == "CLM-TEST001"
        assert result["dispute_type"] == "valuation_disagreement"
        assert result["resolution_type"] == "auto_resolved"
        assert result["status"] == STATUS_DISPUTE_RESOLVED
        assert result["adjusted_amount"] == 16000.0

        repo = ClaimRepository(db_path=seeded_temp_db)
        claim = repo.get_claim("CLM-TEST001")
        assert claim["status"] == STATUS_DISPUTE_RESOLVED

    def test_run_dispute_workflow_escalate(self, seeded_temp_db):
        from claim_agent.db.constants import STATUS_NEEDS_REVIEW
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow

        mock_result = MagicMock()
        mock_result.raw = "Claim escalated for human review. Liability disputed."

        with patch("claim_agent.workflow.dispute_orchestrator.create_dispute_crew") as mock_crew_fn:
            mock_crew = MagicMock()
            mock_crew.kickoff.return_value = mock_result
            mock_crew_fn.return_value = mock_crew

            result = run_dispute_workflow({
                "claim_id": "CLM-TEST001",
                "dispute_type": "liability_determination",
                "dispute_description": "Other driver at fault",
            })

        assert result["resolution_type"] == "escalated"
        assert result["status"] == STATUS_NEEDS_REVIEW

        repo = ClaimRepository(db_path=seeded_temp_db)
        claim = repo.get_claim("CLM-TEST001")
        assert claim["status"] == STATUS_NEEDS_REVIEW


# ---------------------------------------------------------------------------
# DB constants
# ---------------------------------------------------------------------------


class TestDisputeConstants:
    def test_dispute_resolved_status_exists(self):
        from claim_agent.db.constants import (
            CLAIM_STATUSES,
            STATUS_DISPUTE_RESOLVED,
            STATUS_DISPUTED,
        )

        assert STATUS_DISPUTED == "disputed"
        assert STATUS_DISPUTE_RESOLVED == "dispute_resolved"
        assert STATUS_DISPUTED in CLAIM_STATUSES
        assert STATUS_DISPUTE_RESOLVED in CLAIM_STATUSES


# ---------------------------------------------------------------------------
# Webhook mapping
# ---------------------------------------------------------------------------


class TestDisputeWebhook:
    def test_webhook_dispute_events(self):
        from claim_agent.notifications.webhook import _STATUS_TO_EVENT

        assert _STATUS_TO_EVENT["disputed"] == "claim.disputed"
        assert _STATUS_TO_EVENT["dispute_resolved"] == "claim.dispute_resolved"
