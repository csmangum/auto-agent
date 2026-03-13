"""Unit tests for repair authorization webhook dispatch and workflow stages."""

import json
import logging
from unittest.mock import MagicMock, patch

# Import workflow via main_crew first to avoid circular import when tests import stages
import claim_agent.crews.main_crew  # noqa: F401

from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.notifications.webhook import dispatch_repair_authorized_from_workflow_output


def _make_claim_for_stage_tests(repo: ClaimRepository, claim_id: str = "CLM-1") -> str:
    """Create a claim for stage tests (required for checkpoint FK)."""
    return repo.create_claim(ClaimInput(
        policy_number="POL-001",
        vin="VIN123",
        vehicle_year=2022,
        vehicle_make="Test",
        vehicle_model="Car",
        incident_date="2025-06-01",
        incident_description="Hit",
        damage_description="Dent",
        estimated_damage=3000,
    ))


class TestDispatchRepairAuthorizedFromWorkflowOutput:
    """Tests for dispatch_repair_authorized_from_workflow_output."""

    def test_dispatches_when_full_payload_present(self):
        """Webhook is called with correct payload when workflow output has all fields."""
        output = json.dumps({
            "authorization_id": "RA-ABCD1234",
            "claim_id": "CLM-001",
            "shop_id": "SHOP-001",
            "shop_name": "Premier Auto",
            "shop_phone": "555-0100",
            "authorized_amount": 3500.0,
            "shop_webhook_url": "https://shop.example.com/hook",
        })
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_called_once()
            call_kw = mock.call_args[1]
            assert call_kw["claim_id"] == "CLM-001"
            assert call_kw["shop_id"] == "SHOP-001"
            assert call_kw["shop_name"] == "Premier Auto"
            assert call_kw["shop_phone"] == "555-0100"
            assert call_kw["authorized_amount"] == 3500.0
            assert call_kw["authorization_id"] == "RA-ABCD1234"
            assert call_kw["shop_webhook_url"] == "https://shop.example.com/hook"

    def test_dispatches_with_minimal_payload(self):
        """Webhook is called when only authorization_id present (uses defaults for rest)."""
        output = json.dumps({"authorization_id": "RA-MINIMAL"})
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_called_once()
            call_kw = mock.call_args[1]
            assert call_kw["authorization_id"] == "RA-MINIMAL"
            assert call_kw["claim_id"] == ""
            assert call_kw["shop_id"] == ""
            assert call_kw["authorized_amount"] == 0.0

    def test_skips_when_no_authorization_id(self):
        """Webhook is not called when authorization_id is missing."""
        output = json.dumps({"payout_amount": 2100.0, "claim_id": "CLM-001"})
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_not_called()

    def test_skips_when_invalid_json(self):
        """Webhook is not called when workflow output is invalid JSON."""
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output("not valid json", log=log)
            mock.assert_not_called()

    def test_skips_when_output_is_not_dict(self):
        """Webhook is not called when parsed output is not a dict."""
        output = json.dumps(["list", "not", "dict"])
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_not_called()

    def test_handles_null_fields_from_pydantic(self):
        """Webhook uses empty string / 0 when optional fields are null."""
        output = json.dumps({
            "authorization_id": "RA-X",
            "claim_id": None,
            "shop_id": None,
            "shop_name": None,
            "shop_phone": None,
            "authorized_amount": None,
        })
        log = logging.getLogger("test")
        with patch("claim_agent.notifications.webhook.dispatch_repair_authorized") as mock:
            dispatch_repair_authorized_from_workflow_output(output, log=log)
            mock.assert_called_once()
            call_kw = mock.call_args[1]
            assert call_kw["claim_id"] == ""
            assert call_kw["shop_id"] == ""
            assert call_kw["authorized_amount"] == 0.0


class TestParseReopenedOutput:
    """Unit tests for _parse_reopened_output covering all three code paths."""

    def _make_result_with_pydantic(self, target_claim_type: str):
        """Build a mock crew result with a Pydantic ReopenedWorkflowOutput as the last task output."""
        from unittest.mock import MagicMock
        from claim_agent.models.workflow_output import ReopenedWorkflowOutput

        pydantic_output = ReopenedWorkflowOutput(
            target_claim_type=target_claim_type,
            reopening_reason_validated=True,
        )
        task_out = MagicMock()
        task_out.output = pydantic_output
        result = MagicMock()
        result.tasks_output = [task_out]
        return result

    def _make_result_with_raw_json(self, raw: str):
        """Build a mock crew result with a raw JSON string (no Pydantic output)."""
        from unittest.mock import MagicMock

        task_out = MagicMock()
        task_out.output = "plain text"  # not a ReopenedWorkflowOutput
        result = MagicMock()
        result.tasks_output = [task_out]
        result.raw = raw
        return result

    def _make_result_empty(self):
        """Build a mock crew result with no usable output."""
        from unittest.mock import MagicMock

        result = MagicMock()
        result.tasks_output = []
        result.raw = "no useful data here"
        return result

    # --- Pydantic path ---

    def test_pydantic_partial_loss(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_pydantic("partial_loss")
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value

    def test_pydantic_total_loss(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_pydantic("total_loss")
        assert _parse_reopened_output(result) == ClaimType.TOTAL_LOSS.value

    def test_pydantic_bodily_injury(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_pydantic("bodily_injury")
        assert _parse_reopened_output(result) == ClaimType.BODILY_INJURY.value

    def test_pydantic_reopened_circular_defaults_to_partial_loss(self):
        """Pydantic path: circular reopened value must default to partial_loss."""
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_pydantic("reopened")
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value

    # --- Regex fallback path ---

    def test_regex_partial_loss(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_raw_json('{"target_claim_type": "partial_loss", "other": 1}')
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value

    def test_regex_total_loss(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_raw_json('{"target_claim_type": "total_loss"}')
        assert _parse_reopened_output(result) == ClaimType.TOTAL_LOSS.value

    def test_regex_bodily_injury(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_raw_json('{"target_claim_type": "bodily_injury"}')
        assert _parse_reopened_output(result) == ClaimType.BODILY_INJURY.value

    def test_regex_reopened_circular_defaults_to_partial_loss(self):
        """Regex fallback: circular 'reopened' must not be returned; default to partial_loss."""
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_with_raw_json('{"target_claim_type": "reopened"}')
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value

    # --- Default path ---

    def test_default_when_no_usable_output(self):
        from claim_agent.workflow.stages import _parse_reopened_output
        from claim_agent.models.claim import ClaimType

        result = self._make_result_empty()
        assert _parse_reopened_output(result) == ClaimType.PARTIAL_LOSS.value


class TestParseEscalationCrewResult:
    """Unit tests for _parse_escalation_crew_result (pydantic vs output attribute)."""

    def test_extracts_from_pydantic_attribute(self):
        """CrewAI may store output_pydantic result in .pydantic."""
        from claim_agent.models.stage_outputs import EscalationCheckResult
        from claim_agent.workflow.stages import _parse_escalation_crew_result

        decision = EscalationCheckResult(
            needs_review=True,
            escalation_reasons=["low_confidence"],
            priority="medium",
            recommended_action="Review manually.",
            fraud_indicators=[],
        )
        task_out = MagicMock()
        task_out.pydantic = decision
        task_out.output = None
        result = MagicMock(tasks_output=[task_out])

        parsed = _parse_escalation_crew_result(result)
        assert parsed is not None
        assert parsed.needs_review is True
        assert parsed.priority == "medium"

    def test_extracts_from_output_attribute(self):
        """CrewAI may store output_pydantic result in .output (version-dependent)."""
        from claim_agent.models.stage_outputs import EscalationCheckResult
        from claim_agent.workflow.stages import _parse_escalation_crew_result

        decision = EscalationCheckResult(
            needs_review=False,
            escalation_reasons=[],
            priority="low",
            recommended_action="No action needed.",
            fraud_indicators=[],
        )
        task_out = MagicMock()
        task_out.pydantic = None
        task_out.output = decision
        result = MagicMock(tasks_output=[task_out])

        parsed = _parse_escalation_crew_result(result)
        assert parsed is not None
        assert parsed.needs_review is False
        assert parsed.priority == "low"

    def test_returns_none_when_empty_tasks_output(self):
        from claim_agent.workflow.stages import _parse_escalation_crew_result

        result = MagicMock(tasks_output=[])
        assert _parse_escalation_crew_result(result) is None

    def test_returns_none_when_output_not_escalation_check_result(self):
        from claim_agent.workflow.stages import _parse_escalation_crew_result

        task_out = MagicMock()
        task_out.pydantic = None
        task_out.output = "plain text"
        result = MagicMock(tasks_output=[task_out])

        assert _parse_escalation_crew_result(result) is None


class TestEscalationCheckAgentPath:
    """Integration tests for _stage_escalation_check agent path (use_agent=True)."""

    @patch("claim_agent.workflow.stages._kickoff_with_retry")
    @patch("claim_agent.workflow.stages.create_escalation_crew")
    @patch("claim_agent.workflow.stages.get_escalation_config")
    def test_agent_result_used_when_crew_returns_escalation_check_result(
        self, mock_config, mock_create_crew, mock_kickoff, temp_db,
    ):
        """When use_agent=True and crew returns EscalationCheckResult, that decision is used."""
        from claim_agent.context import ClaimContext
        from claim_agent.models.stage_outputs import EscalationCheckResult
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_escalation_check

        mock_config.return_value = {"use_agent": True}
        mock_create_crew.return_value = MagicMock()

        decision = EscalationCheckResult(
            needs_review=True,
            escalation_reasons=["low_confidence"],
            priority="high",
            recommended_action="Review claim manually.",
            fraud_indicators=[],
        )
        task_out = MagicMock()
        task_out.pydantic = decision
        task_out.output = None
        crew_result = MagicMock(tasks_output=[task_out])
        mock_kickoff.return_value = crew_result

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim_for_stage_tests(repo)
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123", "incident_description": "Hit", "damage_description": "Dent"}
        claim_data_with_id = {**claim_data, "id": claim_id}

        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
            claim_type="new",
            raw_output="new\nFirst-time claim.",
            router_confidence=0.5,
        )

        with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_eval:
            result = _stage_escalation_check(wf_ctx)

        mock_eval.assert_not_called()
        assert result is not None
        assert result.get("status") == "needs_review"
        assert wf_ctx.escalation_result is not None
        assert wf_ctx.escalation_result.needs_review is True
        assert wf_ctx.escalation_result.priority == "high"

    @patch("claim_agent.workflow.stages.get_escalation_config")
    def test_use_agent_false_skips_crew_and_uses_rules(self, mock_config, temp_db):
        """When use_agent=False, escalation crew is not called; rules are used."""
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_escalation_check

        mock_config.return_value = {"use_agent": False}

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim_for_stage_tests(repo)
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {
            "vin": "VIN123",
            "incident_description": "Minor damage.",
            "damage_description": "Damage to bumper.",
            "estimated_damage": 500.0,
        }
        claim_data_with_id = {**claim_data, "id": claim_id}

        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
            claim_type="new",
            raw_output="possibly duplicate. Unclear.",
            router_confidence=0.5,
        )

        with patch("claim_agent.workflow.stages.create_escalation_crew") as mock_crew:
            with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_eval:
                mock_eval.return_value = '{"needs_review": true, "escalation_reasons": ["low_confidence"], "priority": "medium", "recommended_action": "Review.", "fraud_indicators": []}'
                result = _stage_escalation_check(wf_ctx)

        mock_crew.assert_not_called()
        mock_eval.assert_called_once()
        assert result is not None
        assert result.get("status") == "needs_review"


class TestRunStage:
    """Unit tests for _run_stage checkpoint wrapper."""

    def test_successful_checkpoint_restore_skips_run(self, temp_db):
        """When checkpoint exists and restores successfully, run is not called."""
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _run_stage

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim_for_stage_tests(repo)
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {**claim_data, "id": claim_id}
        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={"my_stage": json.dumps({"foo": "restored"})},
        )

        restore_called = []
        run_called = []

        def restore(c: _WorkflowCtx, cp: dict) -> None:
            restore_called.append(cp)

        def run(c: _WorkflowCtx) -> dict | None:
            run_called.append(True)
            return None

        result = _run_stage(
            wf_ctx,
            "my_stage",
            restore=restore,
            run=run,
            get_checkpoint_data=lambda c: {"foo": "bar"},
        )

        assert result is None
        assert restore_called == [{"foo": "restored"}]
        assert run_called == []

    def test_corrupt_checkpoint_fallback_and_rerun(self, temp_db):
        """When checkpoint is corrupt, it is invalidated and run is executed."""
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _run_stage

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim_for_stage_tests(repo)
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {**claim_data, "id": claim_id}
        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={"my_stage": "not valid json"},
        )

        run_called = []

        def restore(c: _WorkflowCtx, cp: dict) -> None:
            pass

        def run(c: _WorkflowCtx) -> dict | None:
            run_called.append(True)
            return None

        result = _run_stage(
            wf_ctx,
            "my_stage",
            restore=restore,
            run=run,
            get_checkpoint_data=lambda c: {"foo": "bar"},
        )

        assert result is None
        assert run_called == [True]
        assert "my_stage" not in wf_ctx.checkpoints

    def test_early_return_propagation(self, temp_db):
        """When run returns a dict, it is propagated and checkpoint is not saved."""
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _run_stage

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim_for_stage_tests(repo)
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {**claim_data, "id": claim_id}
        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
        )

        early = {"status": "escalated", "claim_id": claim_id}

        def restore(c: _WorkflowCtx, cp: dict) -> None:
            pass

        def run(c: _WorkflowCtx) -> dict | None:
            return early

        result = _run_stage(
            wf_ctx,
            "my_stage",
            restore=restore,
            run=run,
            get_checkpoint_data=lambda c: {"foo": "bar"},
        )

        assert result == early

    def test_checkpoint_save_after_successful_run(self, temp_db):
        """After successful run, checkpoint is saved via repo."""
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _run_stage

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim_for_stage_tests(repo)
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {**claim_data, "id": claim_id}
        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
        )

        def restore(c: _WorkflowCtx, cp: dict) -> None:
            pass

        def run(c: _WorkflowCtx) -> dict | None:
            return None

        result = _run_stage(
            wf_ctx,
            "my_stage",
            restore=restore,
            run=run,
            get_checkpoint_data=lambda c: {"saved": "data"},
        )

        assert result is None
        cps = ctx.repo.get_task_checkpoints(claim_id, "run-1")
        assert "my_stage" in cps
        assert json.loads(cps["my_stage"]) == {"saved": "data"}


class TestRunCrewStage:
    """Unit tests for _run_crew_stage and _run_crew_stage_body."""

    @patch("claim_agent.workflow.stages._check_token_budget")
    @patch("claim_agent.workflow.stages.create_rental_crew")
    def test_run_crew_stage_saves_checkpoint_after_success(
        self, mock_create_crew, mock_budget, temp_db
    ):
        """_run_crew_stage saves checkpoint with crew output after successful run."""
        from claim_agent.context import ClaimContext
        from claim_agent.models.claim import ClaimType
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _run_crew_stage, create_rental_crew

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim_for_stage_tests(repo)
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {**claim_data, "id": claim_id, "claim_type": ClaimType.PARTIAL_LOSS.value}
        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            claim_type=ClaimType.PARTIAL_LOSS.value,
            workflow_output="prior",
            checkpoints={},
        )

        crew_inst = MagicMock()
        crew_inst.kickoff.return_value = MagicMock(raw="rental output here")
        mock_create_crew.return_value = crew_inst

        result = _run_crew_stage(
            wf_ctx,
            "rental",
            "rental",
            "rental_output",
            create_crew=lambda c: create_rental_crew(c.context.llm),
            get_inputs=lambda c: {"claim_data": json.dumps(c.claim_data_with_id), "workflow_output": c.workflow_output},
            combine_label="Rental workflow output",
        )

        assert result is None
        cps = ctx.repo.get_task_checkpoints(claim_id, "run-1")
        assert "rental" in cps
        cp_data = json.loads(cps["rental"])
        assert cp_data["rental_output"] == "rental output here"

    def test_run_crew_stage_restores_from_checkpoint(self, temp_db):
        """_run_crew_stage restores workflow_output from checkpoint and skips crew."""
        from claim_agent.context import ClaimContext
        from claim_agent.models.claim import ClaimType
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _run_crew_stage, create_rental_crew

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim_for_stage_tests(repo)
        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {**claim_data, "id": claim_id, "claim_type": ClaimType.PARTIAL_LOSS.value}
        wf_ctx = _WorkflowCtx(
            claim_id=claim_id,
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            claim_type=ClaimType.PARTIAL_LOSS.value,
            workflow_output="prior",
            checkpoints={"rental": json.dumps({"rental_output": "cached rental output"})},
        )

        with patch("claim_agent.workflow.stages.create_rental_crew") as mock_create:
            result = _run_crew_stage(
                wf_ctx,
                "rental",
                "rental",
                "rental_output",
                create_crew=lambda c: create_rental_crew(c.context.llm),
                get_inputs=lambda c: {"claim_data": json.dumps(c.claim_data_with_id), "workflow_output": c.workflow_output},
                combine_label="Rental workflow output",
            )

        assert result is None
        assert "cached rental output" in wf_ctx.workflow_output
        mock_create.assert_not_called()


class TestStageEconomicAnalysis:
    """Unit tests for _stage_economic_analysis."""

    @patch("claim_agent.workflow.stages._check_economic_total_loss")
    def test_enriches_claim_data_with_id(self, mock_economic, temp_db):
        """_stage_economic_analysis enriches ctx.claim_data_with_id with economic flags."""
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_economic_analysis

        mock_economic.return_value = {
            "is_economic_total_loss": True,
            "is_catastrophic_event": False,
            "damage_indicates_total_loss": True,
            "damage_is_repairable": False,
            "vehicle_value": 20000,
            "damage_to_value_ratio": 0.95,
        }

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123", "estimated_damage": 19000}
        claim_data_with_id = {**claim_data, "id": "CLM-1"}
        wf_ctx = _WorkflowCtx(
            claim_id="CLM-1",
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
        )

        result = _stage_economic_analysis(wf_ctx)

        assert result is None
        assert wf_ctx.claim_data_with_id["is_economic_total_loss"] is True
        assert wf_ctx.claim_data_with_id["is_catastrophic_event"] is False
        assert wf_ctx.claim_data_with_id["damage_indicates_total_loss"] is True
        assert wf_ctx.claim_data_with_id["damage_is_repairable"] is False
        assert wf_ctx.claim_data_with_id["vehicle_value"] == 20000
        assert wf_ctx.claim_data_with_id["damage_to_value_ratio"] == 0.95


class TestStageFraudPrescreening:
    """Unit tests for _stage_fraud_prescreening."""

    @patch("claim_agent.workflow.stages.detect_fraud_indicators_impl")
    def test_triggers_only_when_ratio_exceeds_threshold(self, mock_detect, temp_db):
        """_stage_fraud_prescreening only runs when damage_to_value_ratio > threshold."""
        from claim_agent.config.settings import PRE_ROUTING_FRAUD_DAMAGE_RATIO
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_fraud_prescreening

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {
            **claim_data,
            "id": "CLM-1",
            "damage_to_value_ratio": PRE_ROUTING_FRAUD_DAMAGE_RATIO + 0.1,
            "is_catastrophic_event": False,
            "damage_indicates_total_loss": False,
        }
        wf_ctx = _WorkflowCtx(
            claim_id="CLM-1",
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
        )

        mock_detect.return_value = json.dumps({"indicators": ["suspicious_timing"]})

        result = _stage_fraud_prescreening(wf_ctx)

        assert result is None
        mock_detect.assert_called_once()
        assert "pre_routing_fraud_indicators" in wf_ctx.claim_data_with_id

    @patch("claim_agent.workflow.stages.detect_fraud_indicators_impl")
    def test_skips_when_ratio_below_threshold(self, mock_detect, temp_db):
        """_stage_fraud_prescreening does not run when ratio <= threshold."""
        from claim_agent.config.settings import PRE_ROUTING_FRAUD_DAMAGE_RATIO
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_fraud_prescreening

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {
            **claim_data,
            "id": "CLM-1",
            "damage_to_value_ratio": PRE_ROUTING_FRAUD_DAMAGE_RATIO - 0.1,
            "is_catastrophic_event": False,
            "damage_indicates_total_loss": False,
        }
        wf_ctx = _WorkflowCtx(
            claim_id="CLM-1",
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
        )

        result = _stage_fraud_prescreening(wf_ctx)

        assert result is None
        mock_detect.assert_not_called()

    @patch("claim_agent.workflow.stages.detect_fraud_indicators_impl")
    def test_skips_when_catastrophic(self, mock_detect, temp_db):
        """_stage_fraud_prescreening does not run when is_catastrophic_event."""
        from claim_agent.config.settings import PRE_ROUTING_FRAUD_DAMAGE_RATIO
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_fraud_prescreening

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123"}
        claim_data_with_id = {
            **claim_data,
            "id": "CLM-1",
            "damage_to_value_ratio": PRE_ROUTING_FRAUD_DAMAGE_RATIO + 0.1,
            "is_catastrophic_event": True,
            "damage_indicates_total_loss": False,
        }
        wf_ctx = _WorkflowCtx(
            claim_id="CLM-1",
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
        )

        result = _stage_fraud_prescreening(wf_ctx)

        assert result is None
        mock_detect.assert_not_called()


class TestStageDuplicateDetection:
    """Unit tests for _stage_duplicate_detection."""

    @patch("claim_agent.workflow.stages._check_for_duplicates")
    def test_rebuilds_inputs_with_enriched_claim_data(self, mock_check, temp_db):
        """_stage_duplicate_detection rebuilds ctx.inputs with claim_data_with_id."""
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.orchestrator import _WorkflowCtx
        from claim_agent.workflow.stages import _stage_duplicate_detection

        mock_check.return_value = []

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        claim_data = {"vin": "VIN123", "incident_description": "Hit", "damage_description": "Dent"}
        claim_data_with_id = {**claim_data, "id": "CLM-1"}
        wf_ctx = _WorkflowCtx(
            claim_id="CLM-1",
            claim_data=claim_data,
            claim_data_with_id=claim_data_with_id,
            inputs={"old": "input"},
            similarity_score_for_escalation=None,
            context=ctx,
            workflow_run_id="run-1",
            workflow_start_time=0.0,
            actor_id="test",
            checkpoints={},
        )

        result = _stage_duplicate_detection(wf_ctx)

        assert result is None
        assert "claim_data" in wf_ctx.inputs
        assert json.loads(wf_ctx.inputs["claim_data"]) == claim_data_with_id
