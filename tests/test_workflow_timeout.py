"""Tests for claim processing wall-clock timeout (C6 pilot-readiness).

Covers:
- ClaimWorkflowTimeoutError exception attributes
- Timeout raised when elapsed time exceeds limit between stages
- Claim marked as STATUS_FAILED on timeout
- claim.timeout webhook dispatched on timeout
- Settings defaults and env-var overrides for timeout knobs
- Per-LLM-call timeout passed through to get_llm()
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.exceptions import ClaimWorkflowTimeoutError
from claim_agent.db.repository import ClaimRepository


# ---------------------------------------------------------------------------
# Exception contract
# ---------------------------------------------------------------------------


class TestClaimWorkflowTimeoutError:
    def test_attributes(self):
        err = ClaimWorkflowTimeoutError("CLM-1", 650.0, 600.0)
        assert err.claim_id == "CLM-1"
        assert err.elapsed_seconds == 650.0
        assert err.timeout_seconds == 600.0

    def test_message_contains_claim_id(self):
        err = ClaimWorkflowTimeoutError("CLM-42", 700.0, 600.0)
        assert "CLM-42" in str(err)

    def test_message_contains_elapsed_and_limit(self):
        err = ClaimWorkflowTimeoutError("CLM-1", 700.0, 600.0)
        assert "700" in str(err)
        assert "600" in str(err)

    def test_is_claim_agent_error(self):
        from claim_agent.exceptions import ClaimAgentError
        err = ClaimWorkflowTimeoutError("CLM-1", 1.0, 1.0)
        assert isinstance(err, ClaimAgentError)


# ---------------------------------------------------------------------------
# Settings defaults
# ---------------------------------------------------------------------------


class TestTimeoutSettings:
    def test_claim_workflow_timeout_default(self):
        from claim_agent.config import get_settings
        s = get_settings()
        assert s.claim_workflow_timeout_seconds == 600

    def test_llm_call_timeout_default(self):
        from claim_agent.config import get_settings
        s = get_settings()
        assert s.llm_call_timeout_seconds == 120

    def test_claim_workflow_timeout_env_override(self, monkeypatch):
        from claim_agent.config import reload_settings
        monkeypatch.setenv("CLAIM_WORKFLOW_TIMEOUT_SECONDS", "300")
        s = reload_settings()
        assert s.claim_workflow_timeout_seconds == 300
        reload_settings()  # reset

    def test_llm_call_timeout_env_override(self, monkeypatch):
        from claim_agent.config import reload_settings
        monkeypatch.setenv("LLM_CALL_TIMEOUT_SECONDS", "60")
        s = reload_settings()
        assert s.llm_call_timeout_seconds == 60
        reload_settings()  # reset


# ---------------------------------------------------------------------------
# Timeout enforcement in run_claim_workflow
# ---------------------------------------------------------------------------


def _make_claim_data() -> dict:
    return {
        "policy_number": "POL-TIMEOUT-01",
        "vin": "TMVINTIMEOUT001",
        "vehicle_year": 2023,
        "vehicle_make": "TestMake",
        "vehicle_model": "TestModel",
        "incident_date": "2025-06-01",
        "incident_description": "Fender bender.",
        "damage_description": "Minor scratch.",
    }


def _mock_router_result(claim_type="new", confidence=0.95):
    from claim_agent.models.claim import RouterOutput

    pydantic_output = RouterOutput(
        claim_type=claim_type,
        confidence=confidence,
        reasoning="test",
    )
    task_output = MagicMock()
    task_output.output = pydantic_output

    result = MagicMock()
    result.raw = json.dumps({"claim_type": claim_type, "confidence": confidence, "reasoning": "test"})
    result.output = result.raw
    result.tasks_output = [task_output]
    return result


def _mock_crew_result(output_text="Crew output"):
    result = MagicMock()
    result.raw = output_text
    result.output = output_text
    result.tasks_output = []
    return result


class TestWorkflowTimeoutEnforcement:
    """Test that run_claim_workflow raises ClaimWorkflowTimeoutError and marks claim failed."""

    @patch("claim_agent.workflow.stages.evaluate_escalation_impl")
    @patch("claim_agent.workflow.stages.create_task_planner_crew")
    @patch("claim_agent.workflow.stages.create_after_action_crew")
    @patch("claim_agent.workflow.stages.create_router_crew")
    @patch("claim_agent.workflow.stages.create_new_claim_crew")
    @patch("claim_agent.workflow.orchestrator.get_llm")
    @patch("claim_agent.workflow.stages.get_router_config")
    @patch("claim_agent.workflow.orchestrator.get_settings")
    @patch("claim_agent.workflow.orchestrator.time")
    def test_timeout_raises_and_marks_failed(
        self,
        mock_time,
        mock_get_settings,
        mock_router_config,
        mock_get_llm,
        mock_new_crew,
        mock_router_crew,
        mock_after_action,
        mock_task_planner,
        mock_escalation,
        temp_db,
    ):
        """When elapsed time exceeds timeout, ClaimWorkflowTimeoutError is raised and
        claim is marked STATUS_FAILED."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.constants import STATUS_FAILED

        # Settings: 30-second timeout
        settings_mock = MagicMock()
        settings_mock.claim_workflow_timeout_seconds = 30
        settings_mock.payment.auto_record_from_settlement = False
        mock_get_settings.return_value = settings_mock

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new")
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("New claim processed")
        mock_new_crew.return_value = new_crew_inst

        mock_task_planner.return_value.kickoff.return_value = _mock_crew_result("Tasks done")
        mock_after_action.return_value.kickoff.return_value = _mock_crew_result("After-action")

        # Simulate time: first call returns 0 (start), subsequent calls return 35 (over limit)
        mock_time.time.side_effect = [0.0] + [35.0] * 50

        with pytest.raises(ClaimWorkflowTimeoutError) as exc_info:
            run_claim_workflow(_make_claim_data(), llm=mock_llm)

        err = exc_info.value
        assert err.claim_id is not None
        assert err.elapsed_seconds >= 30.0
        assert err.timeout_seconds == 30

        # Claim must be marked failed in the DB
        repo = ClaimRepository(db_path=temp_db)
        claim = repo.get_claim(err.claim_id)
        assert claim is not None
        assert claim["status"] == STATUS_FAILED

    @patch("claim_agent.workflow.stages.evaluate_escalation_impl")
    @patch("claim_agent.workflow.stages.create_task_planner_crew")
    @patch("claim_agent.workflow.stages.create_after_action_crew")
    @patch("claim_agent.workflow.stages.create_router_crew")
    @patch("claim_agent.workflow.stages.create_new_claim_crew")
    @patch("claim_agent.workflow.orchestrator.get_llm")
    @patch("claim_agent.workflow.stages.get_router_config")
    @patch("claim_agent.workflow.orchestrator.get_settings")
    def test_timeout_dispatches_webhook(
        self,
        mock_get_settings,
        mock_router_config,
        mock_get_llm,
        mock_new_crew,
        mock_router_crew,
        mock_after_action,
        mock_task_planner,
        mock_escalation,
        temp_db,
    ):
        """On timeout, a claim.timeout webhook is dispatched."""
        from claim_agent.crews.main_crew import run_claim_workflow

        settings_mock = MagicMock()
        settings_mock.claim_workflow_timeout_seconds = 30
        settings_mock.payment.auto_record_from_settlement = False
        mock_get_settings.return_value = settings_mock

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new")
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("New claim processed")
        mock_new_crew.return_value = new_crew_inst

        mock_task_planner.return_value.kickoff.return_value = _mock_crew_result("Tasks done")
        mock_after_action.return_value.kickoff.return_value = _mock_crew_result("After-action")

        with patch("claim_agent.workflow.orchestrator.time") as mock_time, \
             patch("claim_agent.notifications.webhook.dispatch_webhook") as mock_dispatch:
            # First call = start time, rest = over limit
            mock_time.time.side_effect = [0.0] + [35.0] * 50

            with pytest.raises(ClaimWorkflowTimeoutError):
                run_claim_workflow(_make_claim_data(), llm=mock_llm)

        # Webhook should have been called with event "claim.timeout"
        dispatch_calls = mock_dispatch.call_args_list
        timeout_events = [c for c in dispatch_calls if c[0][0] == "claim.timeout"]
        assert len(timeout_events) == 1

        _, payload = timeout_events[0][0]
        assert "claim_id" in payload
        assert "elapsed_seconds" in payload
        assert "timeout_seconds" in payload

    @patch("claim_agent.workflow.stages.evaluate_escalation_impl")
    @patch("claim_agent.workflow.stages.create_task_planner_crew")
    @patch("claim_agent.workflow.stages.create_after_action_crew")
    @patch("claim_agent.workflow.stages.create_router_crew")
    @patch("claim_agent.workflow.stages.create_new_claim_crew")
    @patch("claim_agent.workflow.orchestrator.get_llm")
    @patch("claim_agent.workflow.stages.get_router_config")
    @patch("claim_agent.workflow.orchestrator.get_settings")
    def test_no_timeout_when_within_limit(
        self,
        mock_get_settings,
        mock_router_config,
        mock_get_llm,
        mock_new_crew,
        mock_router_crew,
        mock_after_action,
        mock_task_planner,
        mock_escalation,
        temp_db,
    ):
        """When elapsed time is within the limit, no timeout error occurs."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.constants import STATUS_FAILED

        settings_mock = MagicMock()
        settings_mock.claim_workflow_timeout_seconds = 600  # generous
        settings_mock.payment.auto_record_from_settlement = False
        mock_get_settings.return_value = settings_mock

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new")
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("New claim processed")
        mock_new_crew.return_value = new_crew_inst

        mock_task_planner.return_value.kickoff.return_value = _mock_crew_result("Tasks done")
        mock_after_action.return_value.kickoff.return_value = _mock_crew_result("After-action")

        result = run_claim_workflow(_make_claim_data(), llm=mock_llm)

        assert result["status"] != STATUS_FAILED
        assert "claim_id" in result


# ---------------------------------------------------------------------------
# Per-LLM-call timeout passed through get_llm()
# ---------------------------------------------------------------------------


class TestLLMCallTimeout:
    """Test that get_llm() passes the configured timeout to the LLM instance."""

    def test_llm_receives_timeout_kwarg(self):
        """get_llm() must pass timeout=llm_call_timeout_seconds to LLM constructor."""
        captured_kwargs: dict = {}

        class FakeLLM:
            def __init__(self, *args, **kwargs):
                captured_kwargs.update(kwargs)

        with patch("claim_agent.config.llm.get_settings") as mock_settings, \
             patch("crewai.LLM", FakeLLM):
            s = MagicMock()
            s.llm.api_key = "test-key"
            s.llm.api_base = ""
            s.llm.model_name = "gpt-4o-mini"
            s.llm.cache_enabled = False
            s.llm.anthropic_prompt_cache = False
            s.llm_call_timeout_seconds = 90
            mock_settings.return_value = s

            import claim_agent.config.llm as llm_mod
            llm_mod.get_llm()

        assert captured_kwargs.get("timeout") == 90
