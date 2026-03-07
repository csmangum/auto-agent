"""Tests for resumable workflow checkpointing (issue #70).

Covers:
- Checkpoint CRUD operations on ClaimRepository
- Resume logic in run_claim_workflow
- from_stage invalidation
- No regression for full (non-resume) runs
- MidWorkflowEscalation checkpoint cleanup
- API / CLI from_stage parameter
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.db.database import get_connection
from claim_agent.db.repository import ClaimRepository
from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.models.claim import ClaimInput


def _make_repo(db_path: str) -> ClaimRepository:
    return ClaimRepository(db_path=db_path)


def _make_claim(repo: ClaimRepository) -> str:
    return repo.create_claim(ClaimInput(
        policy_number="POL-CP-001",
        vin="CP1234567890",
        vehicle_year=2022,
        vehicle_make="TestMake",
        vehicle_model="TestModel",
        incident_date="2025-06-01",
        incident_description="Rear-ended at intersection.",
        damage_description="Rear bumper damage.",
        estimated_damage=3000,
    ))


# ============================================================================
# Repository CRUD
# ============================================================================


class TestCheckpointCRUD:
    """Test save / load / delete on task_checkpoints table."""

    def test_save_and_get_checkpoint(self, temp_db):
        repo = _make_repo(temp_db)
        claim_id = _make_claim(repo)

        repo.save_task_checkpoint(claim_id, "run-1", "router", '{"claim_type":"new"}')
        cps = repo.get_task_checkpoints(claim_id, "run-1")

        assert cps == {"router": '{"claim_type":"new"}'}

    def test_save_replaces_existing(self, temp_db):
        repo = _make_repo(temp_db)
        claim_id = _make_claim(repo)

        repo.save_task_checkpoint(claim_id, "run-1", "router", '{"v":1}')
        repo.save_task_checkpoint(claim_id, "run-1", "router", '{"v":2}')

        cps = repo.get_task_checkpoints(claim_id, "run-1")
        assert json.loads(cps["router"])["v"] == 2

    def test_get_returns_empty_for_unknown_run(self, temp_db):
        repo = _make_repo(temp_db)
        claim_id = _make_claim(repo)

        assert repo.get_task_checkpoints(claim_id, "nonexistent") == {}

    def test_multiple_stages(self, temp_db):
        repo = _make_repo(temp_db)
        claim_id = _make_claim(repo)

        repo.save_task_checkpoint(claim_id, "run-1", "router", '"r"')
        repo.save_task_checkpoint(claim_id, "run-1", "escalation_check", '"e"')
        repo.save_task_checkpoint(claim_id, "run-1", "workflow:new", '"w"')

        cps = repo.get_task_checkpoints(claim_id, "run-1")
        assert len(cps) == 3
        assert set(cps.keys()) == {"router", "escalation_check", "workflow:new"}

    def test_delete_all(self, temp_db):
        repo = _make_repo(temp_db)
        claim_id = _make_claim(repo)

        repo.save_task_checkpoint(claim_id, "run-1", "router", '"r"')
        repo.save_task_checkpoint(claim_id, "run-1", "escalation_check", '"e"')
        repo.delete_task_checkpoints(claim_id, "run-1")

        assert repo.get_task_checkpoints(claim_id, "run-1") == {}

    def test_delete_specific_keys(self, temp_db):
        repo = _make_repo(temp_db)
        claim_id = _make_claim(repo)

        repo.save_task_checkpoint(claim_id, "run-1", "router", '"r"')
        repo.save_task_checkpoint(claim_id, "run-1", "escalation_check", '"e"')
        repo.save_task_checkpoint(claim_id, "run-1", "workflow:new", '"w"')

        repo.delete_task_checkpoints(claim_id, "run-1", ["escalation_check", "workflow:new"])

        cps = repo.get_task_checkpoints(claim_id, "run-1")
        assert list(cps.keys()) == ["router"]

    def test_different_runs_isolated(self, temp_db):
        repo = _make_repo(temp_db)
        claim_id = _make_claim(repo)

        repo.save_task_checkpoint(claim_id, "run-1", "router", '"run1"')
        repo.save_task_checkpoint(claim_id, "run-2", "router", '"run2"')

        assert json.loads(repo.get_task_checkpoints(claim_id, "run-1")["router"]) == "run1"
        assert json.loads(repo.get_task_checkpoints(claim_id, "run-2")["router"]) == "run2"

    def test_get_latest_workflow_run_id(self, temp_db):
        repo = _make_repo(temp_db)
        claim_id = _make_claim(repo)

        assert repo.get_latest_workflow_run_id(claim_id) is None

        repo.save_task_checkpoint(claim_id, "run-A", "router", '"a"')
        assert repo.get_latest_workflow_run_id(claim_id) == "run-A"

        repo.save_task_checkpoint(claim_id, "run-B", "router", '"b"')
        latest = repo.get_latest_workflow_run_id(claim_id)
        assert latest == "run-B"

    def test_task_checkpoints_table_exists(self, temp_db):
        with get_connection(temp_db) as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "task_checkpoints" in tables


# ============================================================================
# _checkpoint_keys_to_invalidate helper
# ============================================================================


class TestCheckpointInvalidation:
    """Test the helper that determines which keys to delete for from_stage."""

    def test_invalidate_from_router_deletes_all(self):
        from claim_agent.crews.main_crew import _checkpoint_keys_to_invalidate

        cps = {"router": "r", "escalation_check": "e", "workflow:new": "w", "settlement": "s"}
        keys = _checkpoint_keys_to_invalidate("router", cps)
        assert set(keys) == {"router", "escalation_check", "workflow:new", "settlement"}

    def test_invalidate_from_workflow(self):
        from claim_agent.crews.main_crew import _checkpoint_keys_to_invalidate

        cps = {"router": "r", "escalation_check": "e", "workflow:total_loss": "w", "settlement": "s"}
        keys = _checkpoint_keys_to_invalidate("workflow", cps)
        assert set(keys) == {"workflow:total_loss", "settlement"}

    def test_invalidate_from_settlement(self):
        from claim_agent.crews.main_crew import _checkpoint_keys_to_invalidate

        cps = {"router": "r", "escalation_check": "e", "workflow:new": "w", "settlement": "s"}
        keys = _checkpoint_keys_to_invalidate("settlement", cps)
        assert keys == ["settlement"]

    def test_invalidate_unknown_stage_returns_empty(self):
        from claim_agent.crews.main_crew import _checkpoint_keys_to_invalidate

        keys = _checkpoint_keys_to_invalidate("nonexistent", {"router": "r"})
        assert keys == []


# ============================================================================
# run_claim_workflow checkpoint integration
# ============================================================================


def _mock_router_result(claim_type="new", confidence=0.95, reasoning="test"):
    """Build a MagicMock that _parse_router_output can process."""
    from claim_agent.models.claim import RouterOutput

    pydantic_output = RouterOutput(
        claim_type=claim_type,
        confidence=confidence,
        reasoning=reasoning,
    )
    task_output = MagicMock()
    task_output.output = pydantic_output

    result = MagicMock()
    result.raw = json.dumps({"claim_type": claim_type, "confidence": confidence, "reasoning": reasoning})
    result.output = result.raw
    result.tasks_output = [task_output]
    return result


def _mock_crew_result(output_text="Crew output"):
    result = MagicMock()
    result.raw = output_text
    result.output = output_text
    result.tasks_output = []
    return result


class TestWorkflowCheckpoints:
    """Test that run_claim_workflow saves and restores checkpoints."""

    @patch("claim_agent.crews.main_crew.evaluate_escalation_impl")
    @patch("claim_agent.crews.main_crew.create_router_crew")
    @patch("claim_agent.crews.main_crew.create_new_claim_crew")
    @patch("claim_agent.crews.main_crew.get_llm")
    @patch("claim_agent.crews.main_crew.get_router_config")
    def test_full_run_saves_checkpoints(
        self, mock_router_config, mock_get_llm, mock_new_crew, mock_router_crew,
        mock_escalation, temp_db,
    ):
        from claim_agent.crews.main_crew import run_claim_workflow

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new", 0.95)
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("New claim processed")
        mock_new_crew.return_value = new_crew_inst

        result = run_claim_workflow(
            {
                "policy_number": "POL-100",
                "vin": "CPVIN100",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Fender bender",
                "damage_description": "Minor dent",
            },
            llm=mock_llm,
        )

        assert "workflow_run_id" in result
        wf_run_id = result["workflow_run_id"]

        repo = ClaimRepository(db_path=temp_db)
        cps = repo.get_task_checkpoints(result["claim_id"], wf_run_id)
        assert "router" in cps
        assert "escalation_check" in cps
        assert "workflow:new" in cps

        router_cp = json.loads(cps["router"])
        assert router_cp["claim_type"] == "new"

    @patch("claim_agent.crews.main_crew.evaluate_escalation_impl")
    @patch("claim_agent.crews.main_crew.create_router_crew")
    @patch("claim_agent.crews.main_crew.create_new_claim_crew")
    @patch("claim_agent.crews.main_crew.get_llm")
    @patch("claim_agent.crews.main_crew.get_router_config")
    def test_resume_skips_completed_stages(
        self, mock_router_config, mock_get_llm, mock_new_crew, mock_router_crew,
        mock_escalation, temp_db,
    ):
        from claim_agent.crews.main_crew import run_claim_workflow

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new", 0.95)
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("New claim processed")
        mock_new_crew.return_value = new_crew_inst

        # First run
        result1 = run_claim_workflow(
            {
                "policy_number": "POL-200",
                "vin": "CPVIN200",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Fender bender",
                "damage_description": "Minor dent",
            },
            llm=mock_llm,
        )

        claim_id = result1["claim_id"]
        wf_run_id = result1["workflow_run_id"]

        # Reset call counts
        router_crew_inst.kickoff.reset_mock()
        new_crew_inst.kickoff.reset_mock()

        # Resume from same run — all stages checkpointed, nothing should re-run
        result2 = run_claim_workflow(
            {
                "policy_number": "POL-200",
                "vin": "CPVIN200",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Fender bender",
                "damage_description": "Minor dent",
            },
            llm=mock_llm,
            existing_claim_id=claim_id,
            resume_run_id=wf_run_id,
        )

        router_crew_inst.kickoff.assert_not_called()
        new_crew_inst.kickoff.assert_not_called()
        assert result2["claim_type"] == "new"

    @patch("claim_agent.crews.main_crew.evaluate_escalation_impl")
    @patch("claim_agent.crews.main_crew.create_router_crew")
    @patch("claim_agent.crews.main_crew.create_new_claim_crew")
    @patch("claim_agent.crews.main_crew.get_llm")
    @patch("claim_agent.crews.main_crew.get_router_config")
    def test_from_stage_reruns_invalidated_stages(
        self, mock_router_config, mock_get_llm, mock_new_crew, mock_router_crew,
        mock_escalation, temp_db,
    ):
        from claim_agent.crews.main_crew import run_claim_workflow

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new", 0.95)
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("Run 1 output")
        mock_new_crew.return_value = new_crew_inst

        # First full run
        result1 = run_claim_workflow(
            {
                "policy_number": "POL-300",
                "vin": "CPVIN300",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Fender bender",
                "damage_description": "Minor dent",
            },
            llm=mock_llm,
        )

        claim_id = result1["claim_id"]
        wf_run_id = result1["workflow_run_id"]

        router_crew_inst.kickoff.reset_mock()
        new_crew_inst.kickoff.reset_mock()

        # Change the crew output for re-run
        new_crew_inst.kickoff.return_value = _mock_crew_result("Run 2 output")

        # Resume from "workflow" stage — router should NOT re-run, crew SHOULD
        result2 = run_claim_workflow(
            {
                "policy_number": "POL-300",
                "vin": "CPVIN300",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Fender bender",
                "damage_description": "Minor dent",
            },
            llm=mock_llm,
            existing_claim_id=claim_id,
            resume_run_id=wf_run_id,
            from_stage="workflow",
        )

        router_crew_inst.kickoff.assert_not_called()
        new_crew_inst.kickoff.assert_called_once()
        assert "Run 2 output" in result2["workflow_output"]

    @patch("claim_agent.crews.main_crew.evaluate_escalation_impl")
    @patch("claim_agent.crews.main_crew.create_router_crew")
    @patch("claim_agent.crews.main_crew.create_new_claim_crew")
    @patch("claim_agent.crews.main_crew.get_llm")
    @patch("claim_agent.crews.main_crew.get_router_config")
    def test_failed_stage_not_checkpointed(
        self, mock_router_config, mock_get_llm, mock_new_crew, mock_router_crew,
        mock_escalation, temp_db,
    ):
        from claim_agent.crews.main_crew import run_claim_workflow

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new", 0.95)
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.side_effect = RuntimeError("LLM timeout")
        mock_new_crew.return_value = new_crew_inst

        claim_data = {
            "policy_number": "POL-400",
            "vin": "CPVIN400",
            "vehicle_year": 2023,
            "vehicle_make": "Test",
            "vehicle_model": "Car",
            "incident_date": "2025-06-01",
            "incident_description": "Fender bender",
            "damage_description": "Minor dent",
        }

        with pytest.raises(RuntimeError, match="LLM timeout"):
            run_claim_workflow(claim_data, llm=mock_llm)

        repo = ClaimRepository(db_path=temp_db)
        with get_connection(temp_db) as conn:
            row = conn.execute(
                "SELECT id FROM claims WHERE vin = 'CPVIN400'"
            ).fetchone()
        assert row is not None
        claim_id = row["id"]

        run_id = repo.get_latest_workflow_run_id(claim_id)
        assert run_id is not None

        cps = repo.get_task_checkpoints(claim_id, run_id)

        assert "router" in cps
        assert "escalation_check" in cps
        assert "workflow:new" not in cps

    @patch("claim_agent.crews.main_crew.evaluate_escalation_impl")
    @patch("claim_agent.crews.main_crew.create_router_crew")
    @patch("claim_agent.crews.main_crew.create_new_claim_crew")
    @patch("claim_agent.crews.main_crew.get_llm")
    @patch("claim_agent.crews.main_crew.get_router_config")
    def test_no_resume_params_runs_full_workflow(
        self, mock_router_config, mock_get_llm, mock_new_crew, mock_router_crew,
        mock_escalation, temp_db,
    ):
        """Without resume_run_id, checkpoints from prior runs are ignored."""
        from claim_agent.crews.main_crew import run_claim_workflow

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new", 0.95)
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("Output 1")
        mock_new_crew.return_value = new_crew_inst

        # First run
        result1 = run_claim_workflow(
            {
                "policy_number": "POL-500",
                "vin": "CPVIN500",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Fender bender",
                "damage_description": "Minor dent",
            },
            llm=mock_llm,
        )

        router_crew_inst.kickoff.reset_mock()
        new_crew_inst.kickoff.reset_mock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("Output 2")

        # Second run WITHOUT resume — should re-run everything
        result2 = run_claim_workflow(
            {
                "policy_number": "POL-500",
                "vin": "CPVIN500",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Fender bender",
                "damage_description": "Minor dent",
            },
            llm=mock_llm,
            existing_claim_id=result1["claim_id"],
        )

        router_crew_inst.kickoff.assert_called_once()
        new_crew_inst.kickoff.assert_called_once()
        assert result1["workflow_run_id"] != result2["workflow_run_id"]

    @patch("claim_agent.crews.main_crew.evaluate_escalation_impl")
    @patch("claim_agent.crews.main_crew.create_router_crew")
    @patch("claim_agent.crews.main_crew.create_new_claim_crew")
    @patch("claim_agent.crews.main_crew.get_llm")
    @patch("claim_agent.crews.main_crew.get_router_config")
    def test_mid_workflow_escalation_cleans_checkpoints(
        self, mock_router_config, mock_get_llm, mock_new_crew, mock_router_crew,
        mock_escalation, temp_db,
    ):
        """MidWorkflowEscalation during crew run deletes all checkpoints for the run."""
        from claim_agent.crews.main_crew import run_claim_workflow

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new", 0.95)
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.side_effect = MidWorkflowEscalation(
            reason="Suspicious pattern detected",
            indicators=["indicator1"],
            priority="high",
            claim_id="will-be-overridden",
        )
        mock_new_crew.return_value = new_crew_inst

        result = run_claim_workflow(
            {
                "policy_number": "POL-600",
                "vin": "CPVIN600",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Suspicious incident",
                "damage_description": "Major damage",
            },
            llm=mock_llm,
        )

        assert result["status"] == "needs_review"

        repo = ClaimRepository(db_path=temp_db)
        cps = repo.get_task_checkpoints(
            result["claim_id"], result["workflow_run_id"],
        )
        assert cps == {}, "Checkpoints should be cleared after mid-workflow escalation"

    @patch("claim_agent.crews.main_crew.evaluate_escalation_impl")
    @patch("claim_agent.crews.main_crew.create_router_crew")
    @patch("claim_agent.crews.main_crew.create_new_claim_crew")
    @patch("claim_agent.crews.main_crew.get_llm")
    @patch("claim_agent.crews.main_crew.get_router_config")
    def test_from_stage_without_resume_run_id_runs_full(
        self, mock_router_config, mock_get_llm, mock_new_crew, mock_router_crew,
        mock_escalation, temp_db,
    ):
        """from_stage without resume_run_id is ignored and a full run executes."""
        from claim_agent.crews.main_crew import run_claim_workflow

        mock_router_config.return_value = {"confidence_threshold": 0.7}
        mock_escalation.return_value = json.dumps({"needs_review": False})

        mock_llm = MagicMock()
        mock_llm.model = "test-model"
        mock_get_llm.return_value = mock_llm

        router_crew_inst = MagicMock()
        router_crew_inst.kickoff.return_value = _mock_router_result("new", 0.95)
        mock_router_crew.return_value = router_crew_inst

        new_crew_inst = MagicMock()
        new_crew_inst.kickoff.return_value = _mock_crew_result("Processed")
        mock_new_crew.return_value = new_crew_inst

        result = run_claim_workflow(
            {
                "policy_number": "POL-700",
                "vin": "CPVIN700",
                "vehicle_year": 2023,
                "vehicle_make": "Test",
                "vehicle_model": "Car",
                "incident_date": "2025-06-01",
                "incident_description": "Normal incident",
                "damage_description": "Minor dent",
            },
            llm=mock_llm,
            from_stage="workflow",
        )

        router_crew_inst.kickoff.assert_called_once()
        new_crew_inst.kickoff.assert_called_once()
        assert result["claim_type"] == "new"


# ============================================================================
# API from_stage parameter
# ============================================================================


class TestReprocessAPIFromStage:
    """Test the reprocess endpoint with from_stage query param."""

    def test_reprocess_invalid_from_stage_returns_400(self, temp_db):
        from fastapi.testclient import TestClient
        from claim_agent.api.server import app

        client = TestClient(app)
        import os
        os.environ["API_KEYS"] = "sk-sup:supervisor"

        try:
            resp = client.post(
                "/api/claims/CLM-001/reprocess?from_stage=bogus",
                headers={"X-API-Key": "sk-sup"},
            )
            assert resp.status_code == 400
            assert "from_stage" in resp.json()["detail"]
        finally:
            os.environ.pop("API_KEYS", None)

    def test_reprocess_valid_from_stage_accepted(self, temp_db):
        from fastapi.testclient import TestClient
        from claim_agent.api.server import app

        client = TestClient(app)
        import os
        os.environ["API_KEYS"] = "sk-sup:supervisor"

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim(repo)

        try:
            with patch("claim_agent.api.routes.claims.run_claim_workflow") as mock_wf:
                mock_wf.return_value = {"claim_id": claim_id, "status": "open"}
                resp = client.post(
                    f"/api/claims/{claim_id}/reprocess?from_stage=workflow",
                    headers={"X-API-Key": "sk-sup"},
                )
            assert resp.status_code == 200
            call_kwargs = mock_wf.call_args[1]
            assert call_kwargs.get("from_stage") is None or call_kwargs.get("from_stage") == "workflow"
        finally:
            os.environ.pop("API_KEYS", None)


# ============================================================================
# CLI --from-stage flag
# ============================================================================


class TestReprocessCLIFromStage:
    """Test the CLI --from-stage flag for cmd_reprocess."""

    def test_invalid_from_stage_exits_nonzero(self, temp_db):
        from claim_agent.main import cmd_reprocess

        with pytest.raises(SystemExit) as exc_info:
            cmd_reprocess("CLM-DOES-NOT-MATTER", from_stage="bogus_stage")
        assert exc_info.value.code == 1

    def test_from_stage_no_checkpoints_falls_back_to_full(self, temp_db):
        from claim_agent.main import cmd_reprocess

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim(repo)

        with patch("claim_agent.crews.main_crew.run_claim_workflow") as mock_wf:
            mock_wf.return_value = {"claim_id": claim_id, "status": "open"}
            cmd_reprocess(claim_id, from_stage="router")

        call_kwargs = mock_wf.call_args[1]
        assert call_kwargs["resume_run_id"] is None
        assert call_kwargs["from_stage"] is None

    def test_main_parses_from_stage_flag(self, temp_db):
        import sys
        from claim_agent.main import main

        repo = ClaimRepository(db_path=temp_db)
        claim_id = _make_claim(repo)

        with patch("claim_agent.main.cmd_reprocess") as mock_cmd:
            with patch.object(sys, "argv", ["claim-agent", "reprocess", claim_id, "--from-stage", "settlement"]):
                main()

        mock_cmd.assert_called_once_with(claim_id, from_stage="settlement")
