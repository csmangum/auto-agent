"""Tests for deterministic BI post-crew validation (PIP and minor gates)."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.models.claim import ClaimType
from claim_agent.models.workflow_output import BIWorkflowOutput
from claim_agent.workflow.bi_post_crew_validation import (
    extract_bi_workflow_output_from_crew_result,
    maybe_escalate_bodily_injury_post_crew,
)


def _fake_context(repo: MagicMock) -> MagicMock:
    ctx = MagicMock()
    ctx.repo = repo
    ctx.metrics = MagicMock()
    ctx.llm = None
    return ctx


class TestExtractBIWorkflowOutput:
    def test_extracts_pydantic_from_last_task(self):
        bio = BIWorkflowOutput(
            payout_amount=5000.0,
            medical_charges=2000.0,
            pain_suffering=3000.0,
        )
        result = SimpleNamespace(tasks_output=[SimpleNamespace(output="x"), SimpleNamespace(output=bio)])
        assert extract_bi_workflow_output_from_crew_result(result) == bio

    def test_validates_dict_output(self):
        d = {
            "payout_amount": 100.0,
            "medical_charges": 50.0,
            "pain_suffering": 50.0,
        }
        result = SimpleNamespace(tasks_output=[SimpleNamespace(output=d)])
        out = extract_bi_workflow_output_from_crew_result(result)
        assert out is not None
        assert out.payout_amount == 100.0


class TestMaybeEscalateBodilyInjuryPostCrew:
    def test_non_bi_claim_type_returns_none(self):
        assert (
            maybe_escalate_bodily_injury_post_crew(
                claim_type="partial_loss",
                claim_id="C1",
                claim_data={},
                workflow_result=SimpleNamespace(tasks_output=[]),
                routed_output="",
                raw_output="",
                context=MagicMock(),
                workflow_start_time=0.0,
                workflow_run_id=None,
                actor_id=None,
            )
            is None
        )

    def test_skips_when_no_structured_output(self):
        assert (
            maybe_escalate_bodily_injury_post_crew(
                claim_type=ClaimType.BODILY_INJURY.value,
                claim_id="C1",
                claim_data={"policy_number": "P1", "loss_state": "CA"},
                workflow_result=SimpleNamespace(tasks_output=[]),
                routed_output="text",
                raw_output="",
                context=MagicMock(),
                workflow_start_time=0.0,
                workflow_run_id=None,
                actor_id=None,
            )
            is None
        )

    @patch("claim_agent.workflow.bi_post_crew_validation._handle_mid_workflow_escalation")
    def test_escalates_when_pip_not_exhausted_fl(self, mock_handle: MagicMock):
        mock_handle.return_value = {"status": "needs_review"}
        bio = BIWorkflowOutput(
            payout_amount=5000.0,
            medical_charges=5000.0,
            pain_suffering=2500.0,
        )
        result = SimpleNamespace(tasks_output=[SimpleNamespace(output=bio)])
        repo = MagicMock()
        ctx = _fake_context(repo)
        out = maybe_escalate_bodily_injury_post_crew(
            claim_type=ClaimType.BODILY_INJURY.value,
            claim_id="C-FL",
            claim_data={"policy_number": "P1", "loss_state": "FL"},
            workflow_result=result,
            routed_output="crew out",
            raw_output="router",
            context=ctx,
            workflow_start_time=0.0,
            workflow_run_id="run-1",
            actor_id=None,
        )
        assert out == {"status": "needs_review"}
        mock_handle.assert_called_once()
        exc = mock_handle.call_args.args[0]
        assert isinstance(exc, MidWorkflowEscalation)
        assert exc.reason == "pip_medpay_not_exhausted"

    @patch("claim_agent.workflow.bi_post_crew_validation._handle_mid_workflow_escalation")
    def test_escalates_minor_without_court_order(self, mock_handle: MagicMock):
        mock_handle.return_value = {"status": "needs_review"}
        bio = BIWorkflowOutput(
            payout_amount=2000.0,
            medical_charges=1000.0,
            pain_suffering=1000.0,
        )
        result = SimpleNamespace(tasks_output=[SimpleNamespace(output=bio)])
        ctx = _fake_context(MagicMock())
        out = maybe_escalate_bodily_injury_post_crew(
            claim_type=ClaimType.BODILY_INJURY.value,
            claim_id="C-MIN",
            claim_data={
                "policy_number": "P1",
                "loss_state": "CA",
                "claimant_age": 10,
                "minor_court_approval_obtained": False,
            },
            workflow_result=result,
            routed_output="crew out",
            raw_output="router",
            context=ctx,
            workflow_start_time=0.0,
            workflow_run_id=None,
            actor_id=None,
        )
        assert out == {"status": "needs_review"}
        assert mock_handle.call_args.args[0].reason == "minor_settlement_court_approval_required"

    def test_minor_allowed_when_court_flag_on_claim(self):
        bio = BIWorkflowOutput(
            payout_amount=2000.0,
            medical_charges=1000.0,
            pain_suffering=1000.0,
        )
        result = SimpleNamespace(tasks_output=[SimpleNamespace(output=bio)])
        ctx = _fake_context(MagicMock())
        out = maybe_escalate_bodily_injury_post_crew(
            claim_type=ClaimType.BODILY_INJURY.value,
            claim_id="C-MIN-OK",
            claim_data={
                "policy_number": "P1",
                "loss_state": "CA",
                "claimant_age": 10,
                "minor_court_approval_obtained": True,
            },
            workflow_result=result,
            routed_output="crew out",
            raw_output="router",
            context=ctx,
            workflow_start_time=0.0,
            workflow_run_id=None,
            actor_id=None,
        )
        assert out is None


class TestCalculateBISettlementWithLOE:
    """Loss of earnings integrated into calculate_bi_settlement (unit)."""

    def test_loe_increases_total(self):
        from claim_agent.tools.bodily_injury_logic import calculate_bi_settlement_impl

        base = json.loads(
            calculate_bi_settlement_impl(
                claim_id="C1",
                policy_number="",
                medical_charges=1000.0,
                injury_severity="moderate",
                pain_suffering_multiplier=1.5,
                loss_of_earnings=0.0,
            )
        )
        with_loe = json.loads(
            calculate_bi_settlement_impl(
                claim_id="C1",
                policy_number="",
                medical_charges=1000.0,
                injury_severity="moderate",
                pain_suffering_multiplier=1.5,
                loss_of_earnings=500.0,
            )
        )
        assert with_loe["loss_of_earnings"] == 500.0
        assert with_loe["economic_specials"] == 1500.0
        assert with_loe["pain_suffering"] == base["pain_suffering"]
        assert with_loe["total_demand"] == base["total_demand"] + 500.0
