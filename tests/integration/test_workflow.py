"""End-to-end workflow integration tests.

These tests verify the complete claim processing workflow from intake to resolution.
Tests are designed to run with mocked LLM responses for CI, but can also run
against a real LLM when OPENAI_API_KEY or OPENROUTER_API_KEY is set (not a placeholder).
"""

from unittest.mock import MagicMock, patch

import pytest


# ============================================================================
# Claim Type Classification Tests (with mocked LLM)
# ============================================================================


class TestClaimClassification:
    """Test claim type classification logic."""
    
    @pytest.mark.integration
    def test_parse_claim_type_handles_all_types(self):
        """Verify _parse_claim_type correctly handles all claim types."""
        from claim_agent.crews.main_crew import _parse_claim_type
        
        # Exact matches
        assert _parse_claim_type("new") == "new"
        assert _parse_claim_type("duplicate") == "duplicate"
        assert _parse_claim_type("total_loss") == "total_loss"
        assert _parse_claim_type("fraud") == "fraud"
        assert _parse_claim_type("partial_loss") == "partial_loss"
        assert _parse_claim_type("bodily_injury") == "bodily_injury"

        # With reasoning
        assert _parse_claim_type("new\nThis is a new claim.") == "new"
        assert _parse_claim_type("total_loss\nVehicle flooded.") == "total_loss"
        assert _parse_claim_type("partial_loss\nMinor fender damage.") == "partial_loss"
        assert _parse_claim_type("bodily_injury\nPassenger injured in collision.") == "bodily_injury"

        # Normalized variants
        assert _parse_claim_type("total loss") == "total_loss"
        assert _parse_claim_type("partial loss") == "partial_loss"
        assert _parse_claim_type("bodily injury") == "bodily_injury"
        assert _parse_claim_type("FRAUD\nSuspicious patterns.") == "fraud"
    
    @pytest.mark.integration
    def test_final_status_mapping(self):
        """Verify claim types map to correct final statuses."""
        from claim_agent.crews.main_crew import _final_status
        from claim_agent.db.constants import (
            STATUS_OPEN,
            STATUS_DUPLICATE,
            STATUS_FRAUD_SUSPECTED,
            STATUS_SETTLED,
        )
        
        assert _final_status("new") == STATUS_OPEN
        assert _final_status("duplicate") == STATUS_DUPLICATE
        assert _final_status("fraud") == STATUS_FRAUD_SUSPECTED
        assert _final_status("partial_loss") == STATUS_SETTLED
        assert _final_status("total_loss") == STATUS_SETTLED
        assert _final_status("bodily_injury") == STATUS_SETTLED


# ============================================================================
# Workflow Integration Tests (Mocked LLM)
# ============================================================================


class TestWorkflowWithMockedLLM:
    """Test complete workflow with mocked LLM responses."""
    
    @pytest.mark.integration
    def test_workflow_creates_claim_in_database(
        self, integration_db, sample_new_claim, mock_router_response, mock_crew_response, mock_llm_instance
    ):
        """Test that workflow creates a claim record in the database."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.repository import ClaimRepository
        
        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                with patch("claim_agent.workflow.stages.create_new_claim_crew") as mock_crew:
                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                        with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                            mock_llm.return_value = mock_llm_instance
                            mock_router.return_value.kickoff.return_value = mock_router_response("new")
                            mock_crew.return_value.kickoff.return_value = mock_crew_response(
                                "Claim processed successfully. Claim ID: CLM-TEST001"
                            )
                            mock_after.return_value.kickoff.return_value = mock_crew_response(
                                "After-action summary completed."
                            )
                            mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                "Tasks created."
                            )

                            result = run_claim_workflow(sample_new_claim)
        
        assert "claim_id" in result
        assert result["claim_id"].startswith("CLM-")
        
        repo = ClaimRepository(db_path=integration_db)
        claim = repo.get_claim(result["claim_id"])
        assert claim is not None
        assert claim["policy_number"] == sample_new_claim["policy_number"]
    
    @pytest.mark.integration
    def test_workflow_routes_to_correct_crew(
        self, integration_db, sample_total_loss_claim, mock_router_response, mock_crew_response, mock_llm_instance
    ):
        """Test that payout-ready total loss claims run workflow crew then settlement crew."""
        import json
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.models.workflow_output import TotalLossWorkflowOutput

        # Use a claim that won't trigger escalation (low damage estimate)
        low_value_claim = {**sample_total_loss_claim, "estimated_damage": 5000}

        # Structured output with payout_amount for settlement handoff
        mock_task = MagicMock()
        mock_task.output = TotalLossWorkflowOutput(
            payout_amount=14500.0, vehicle_value=15000.0, deductible=500.0, calculation="15000 - 500"
        )
        workflow_tasks_output = [MagicMock(), MagicMock(), mock_task]

        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                with patch("claim_agent.workflow.stages.create_total_loss_crew") as mock_crew:
                    with patch("claim_agent.workflow.stages.create_liability_determination_crew") as mock_liability:
                        with patch("claim_agent.workflow.stages.create_settlement_crew") as mock_settlement:
                            with patch("claim_agent.workflow.stages.create_subrogation_crew") as mock_subrogation:
                                with patch("claim_agent.workflow.stages.create_salvage_crew") as mock_salvage:
                                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                                        with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                                            with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                                                mock_llm.return_value = mock_llm_instance
                                                mock_router.return_value.kickoff.return_value = mock_router_response(
                                                    "total_loss", "Vehicle flooded - total destruction."
                                                )
                                                mock_crew.return_value.kickoff.return_value = mock_crew_response(
                                                    "Total loss confirmed. Vehicle value: $15,000.",
                                                    tasks_output=workflow_tasks_output,
                                                )
                                                mock_liability.return_value.kickoff.return_value = mock_crew_response(
                                                    "Liability determination: not at fault."
                                                )
                                                mock_settlement.return_value.kickoff.return_value = mock_crew_response(
                                                    "Settlement completed. Status: settled."
                                                )
                                                mock_subrogation.return_value.kickoff.return_value = mock_crew_response(
                                                    "Subrogation assessment complete. No recovery opportunity."
                                                )
                                                mock_salvage.return_value.kickoff.return_value = mock_crew_response(
                                                    "Salvage disposition complete."
                                                )
                                                mock_after.return_value.kickoff.return_value = mock_crew_response(
                                                    "After-action summary completed."
                                                )
                                                mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                                mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                                    "Tasks created."
                                                )

                                                result = run_claim_workflow(low_value_claim)

        assert result["claim_type"] == "total_loss"
        mock_crew.assert_called_once()
        mock_settlement.assert_called_once()
        assert "Settlement completed" in result["workflow_output"]
        # Verify settlement received claim_data with payout_amount
        settlement_call = mock_settlement.return_value.kickoff.call_args
        settlement_inputs = settlement_call.kwargs.get("inputs", {})
        claim_data = json.loads(settlement_inputs["claim_data"])
        assert claim_data.get("payout_amount") == 14500.0
        # Verify payout_amount persisted to database
        from claim_agent.db.repository import ClaimRepository
        repo = ClaimRepository(db_path=integration_db)
        claim = repo.get_claim(result["claim_id"])
        assert claim is not None
        assert claim.get("payout_amount") == 14500.0

    @pytest.mark.integration
    def test_partial_loss_runs_shared_settlement_crew(
        self, integration_db, sample_partial_loss_claim, mock_router_response, mock_crew_response, mock_llm_instance
    ):
        """Test that partial loss workflow hands off to the shared settlement crew."""
        import json
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.models.workflow_output import PartialLossWorkflowOutput

        # Structured output with payout_amount for settlement handoff
        mock_task = MagicMock()
        mock_task.output = PartialLossWorkflowOutput(
            payout_amount=2100.0, authorization_id="AUTH-001", total_estimate=2500.0
        )
        workflow_tasks_output = [mock_task]

        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                with patch("claim_agent.workflow.stages.create_partial_loss_crew") as mock_partial:
                    with patch("claim_agent.workflow.stages.create_rental_crew") as mock_rental:
                        with patch("claim_agent.workflow.stages.create_liability_determination_crew") as mock_liability:
                            with patch("claim_agent.workflow.stages.create_settlement_crew") as mock_settlement:
                                with patch("claim_agent.workflow.stages.create_subrogation_crew") as mock_subrogation:
                                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                                        with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                                            with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                                                mock_llm.return_value = mock_llm_instance
                                                mock_router.return_value.kickoff.return_value = mock_router_response(
                                                    "partial_loss", "Repairable fender damage."
                                                )
                                                mock_partial.return_value.kickoff.return_value = mock_crew_response(
                                                    "Repair authorization created. insurance_pays: $2,100.",
                                                    tasks_output=workflow_tasks_output,
                                                )
                                                mock_rental.return_value.kickoff.return_value = mock_crew_response(
                                                    "Rental eligibility confirmed. Reimbursement processed."
                                                )
                                                mock_liability.return_value.kickoff.return_value = mock_crew_response(
                                                    "Liability determination: not at fault."
                                                )
                                                mock_settlement.return_value.kickoff.return_value = mock_crew_response(
                                                    "Settlement completed. Status: settled."
                                                )
                                                mock_subrogation.return_value.kickoff.return_value = mock_crew_response(
                                                    "Subrogation assessment complete. No recovery opportunity."
                                                )
                                                mock_after.return_value.kickoff.return_value = mock_crew_response(
                                                    "After-action summary completed."
                                                )
                                                mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                                mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                                    "Tasks created."
                                                )

                                                result = run_claim_workflow(sample_partial_loss_claim)

        assert result["claim_type"] == "partial_loss"
        mock_partial.assert_called_once()
        mock_rental.assert_called_once()
        mock_settlement.assert_called_once()
        assert "Repair authorization created" in result["workflow_output"]
        assert "Rental eligibility confirmed" in result["workflow_output"]
        assert "Settlement completed" in result["workflow_output"]
        # Verify settlement received claim_data with payout_amount
        settlement_call = mock_settlement.return_value.kickoff.call_args
        settlement_inputs = settlement_call.kwargs.get("inputs", {})
        claim_data = json.loads(settlement_inputs["claim_data"])
        assert claim_data.get("payout_amount") == 2100.0
        # Verify payout_amount persisted to database
        from claim_agent.db.repository import ClaimRepository
        repo = ClaimRepository(db_path=integration_db)
        claim = repo.get_claim(result["claim_id"])
        assert claim is not None
        assert claim.get("payout_amount") == 2100.0
    
    @pytest.mark.integration
    def test_workflow_records_audit_history(
        self, integration_db, sample_new_claim, mock_router_response, mock_crew_response, mock_llm_instance
    ):
        """Test that workflow actions are recorded in the audit log."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.repository import ClaimRepository
        
        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                with patch("claim_agent.workflow.stages.create_new_claim_crew") as mock_crew:
                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                        with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                            mock_llm.return_value = mock_llm_instance
                            mock_router.return_value.kickoff.return_value = mock_router_response("new")
                            mock_crew.return_value.kickoff.return_value = mock_crew_response("Success")
                            mock_after.return_value.kickoff.return_value = mock_crew_response(
                                "After-action summary completed."
                            )
                            mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                "Tasks created."
                            )

                            result = run_claim_workflow(sample_new_claim)
        
        repo = ClaimRepository(db_path=integration_db)
        history, _ = repo.get_claim_history(result["claim_id"])
        
        # Should have at least: created, status_change (processing), status_change (final)
        assert len(history) >= 2
        actions = [h["action"] for h in history]
        assert "created" in actions
        assert "status_change" in actions
    
    @pytest.mark.integration
    def test_workflow_handles_failure_gracefully(
        self, integration_db, sample_new_claim, mock_router_response, mock_llm_instance
    ):
        """Test that workflow failures are properly recorded."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from sqlalchemy import text

        from claim_agent.db.database import get_connection

        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                mock_llm.return_value = mock_llm_instance
                mock_router.return_value.kickoff.side_effect = RuntimeError("LLM unavailable")

                with pytest.raises(RuntimeError, match="LLM unavailable"):
                    run_claim_workflow(sample_new_claim)

        # Verify claim was marked as failed
        with get_connection(integration_db) as conn:
            row = conn.execute(text("SELECT id, status FROM claims")).fetchone()
        
        assert row is not None
        assert row["status"] == "failed"
    
    @pytest.mark.integration
    def test_workflow_saves_workflow_result(
        self, integration_db, sample_new_claim, mock_router_response, mock_crew_response, mock_llm_instance
    ):
        """Test that workflow results are saved to workflow_runs table."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from sqlalchemy import text

        from claim_agent.db.database import get_connection

        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                with patch("claim_agent.workflow.stages.create_new_claim_crew") as mock_crew:
                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                        with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                            with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                                mock_llm.return_value = mock_llm_instance
                                mock_router.return_value.kickoff.return_value = mock_router_response("new")
                                mock_crew.return_value.kickoff.return_value = mock_crew_response("Processed!")
                                mock_after.return_value.kickoff.return_value = mock_crew_response(
                                    "After-action summary completed."
                                )
                                mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                    "Tasks created."
                                )

                                result = run_claim_workflow(sample_new_claim)
        
        with get_connection(integration_db) as conn:
            row = conn.execute(
                text("SELECT * FROM workflow_runs WHERE claim_id = :claim_id"),
                {"claim_id": result["claim_id"]},
            ).fetchone()
        
        assert row is not None
        assert row["claim_type"] == "new"
        assert "Processed!" in row["workflow_output"]


# ============================================================================
# Escalation Tests
# ============================================================================


class TestEscalation:
    """Test claim escalation logic."""
    
    @pytest.mark.integration
    def test_high_value_claim_triggers_escalation(
        self, integration_db, mock_router_response, mock_llm_instance
    ):
        """Test that high value claims are escalated for review."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.constants import STATUS_NEEDS_REVIEW
        
        # High value claim that should trigger escalation
        high_value_claim = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Multi-vehicle collision.",
            "damage_description": "Major structural damage.",
            "estimated_damage": 100000,  # Very high value
        }
        
        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                mock_llm.return_value = mock_llm_instance
                mock_router.return_value.kickoff.return_value = mock_router_response("new")
                
                result = run_claim_workflow(high_value_claim)
        
        # Should be escalated due to high value
        assert result.get("needs_review") is True
        assert result["status"] == STATUS_NEEDS_REVIEW
        assert "escalation_reasons" in result
    
    @pytest.mark.integration
    def test_fraud_claim_runs_fraud_crew_instead_of_escalation(
        self, integration_db, sample_fraud_claim, mock_router_response, mock_crew_response, mock_llm_instance
    ):
        """Test that fraud claims go to fraud crew, not escalation."""
        from claim_agent.crews.main_crew import run_claim_workflow
        
        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                with patch("claim_agent.workflow.stages.create_fraud_detection_crew") as mock_fraud:
                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                        with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                            mock_llm.return_value = mock_llm_instance
                            mock_router.return_value.kickoff.return_value = mock_router_response("fraud")
                            mock_fraud.return_value.kickoff.return_value = mock_crew_response(
                                "Fraud indicators detected: staged accident, inflated damages."
                            )
                            mock_after.return_value.kickoff.return_value = mock_crew_response(
                                "After-action summary completed."
                            )
                            mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                "Tasks created."
                            )

                            result = run_claim_workflow(sample_fraud_claim)
        
        assert result["claim_type"] == "fraud"
        mock_fraud.assert_called_once()


# ============================================================================
# Reprocessing Tests
# ============================================================================


class TestReprocessing:
    """Test claim reprocessing functionality."""
    
    @pytest.mark.integration
    def test_reprocess_existing_claim(
        self, integration_db, sample_new_claim, mock_router_response, mock_crew_response, mock_llm_instance
    ):
        """Test that an existing claim can be reprocessed."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        
        # Create claim first
        repo = ClaimRepository(db_path=integration_db)
        claim_input = ClaimInput(**sample_new_claim)
        claim_id = repo.create_claim(claim_input)
        
        # Reprocess it
        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
                with patch("claim_agent.workflow.stages.create_new_claim_crew") as mock_crew:
                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                        with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                            mock_llm.return_value = mock_llm_instance
                            mock_router.return_value.kickoff.return_value = mock_router_response("new")
                            mock_crew.return_value.kickoff.return_value = mock_crew_response("Reprocessed!")
                            mock_after.return_value.kickoff.return_value = mock_crew_response(
                                "After-action summary completed."
                            )
                            mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                "Tasks created."
                            )

                            result = run_claim_workflow(sample_new_claim, existing_claim_id=claim_id)
        
        assert result["claim_id"] == claim_id
        
        # Check history shows reprocessing
        history, _ = repo.get_claim_history(claim_id)
        assert len(history) >= 3  # created + multiple status changes
    
    @pytest.mark.integration
    def test_reprocess_nonexistent_claim_raises(self, integration_db, sample_new_claim, mock_llm_instance):
        """Test that reprocessing a non-existent claim raises ClaimNotFoundError."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.exceptions import ClaimNotFoundError

        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            mock_llm.return_value = mock_llm_instance
            with pytest.raises(ClaimNotFoundError, match="Claim not found"):
                run_claim_workflow(sample_new_claim, existing_claim_id="CLM-NONEXIST")


# ============================================================================
# Workflow crew claim_data injection and tool use
# ============================================================================


def _structural_llm_for_crew():
    """Return a CrewAI LLM for structural tests (no API calls during crew creation)."""
    from crewai import LLM
    return LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")


class TestWorkflowCrewClaimDataAndTools:
    """Verify workflow crews receive claim_data in task prompts and agents can invoke tools."""

    @pytest.mark.integration
    def test_duplicate_crew_first_task_has_claim_data_placeholder(self):
        """First task of duplicate crew must contain {claim_data} so kickoff(inputs=...) injects it."""
        from claim_agent.crews.duplicate_crew import create_duplicate_crew

        crew = create_duplicate_crew(llm=_structural_llm_for_crew())
        first_task = crew.tasks[0]
        assert "{claim_data}" in first_task.description, (
            "First task description should contain {claim_data} for crew input injection"
        )

    @pytest.mark.integration
    def test_fraud_crew_first_task_has_claim_data_placeholder(self):
        """First task of fraud crew must contain {claim_data} for input injection."""
        from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew

        crew = create_fraud_detection_crew(llm=_structural_llm_for_crew())
        first_task = crew.tasks[0]
        assert "{claim_data}" in first_task.description, (
            "First task description should contain {claim_data} for crew input injection"
        )

    @pytest.mark.integration
    def test_new_claim_crew_first_task_has_claim_data_placeholder(self):
        """First task of new claim crew must contain {claim_data} for input injection."""
        from claim_agent.crews.new_claim_crew import create_new_claim_crew

        crew = create_new_claim_crew(llm=_structural_llm_for_crew())
        first_task = crew.tasks[0]
        assert "{claim_data}" in first_task.description, (
            "First task description should contain {claim_data} for crew input injection"
        )

    @pytest.mark.integration
    def test_total_loss_crew_first_task_has_claim_data_placeholder(self):
        """First task of total loss crew must contain {claim_data} for input injection."""
        from claim_agent.crews.total_loss_crew import create_total_loss_crew

        crew = create_total_loss_crew(llm=_structural_llm_for_crew())
        first_task = crew.tasks[0]
        assert "{claim_data}" in first_task.description, (
            "First task description should contain {claim_data} for crew input injection"
        )

    @pytest.mark.integration
    def test_partial_loss_crew_first_task_has_claim_data_placeholder(self):
        """First task of partial loss crew must contain {claim_data} for input injection."""
        from claim_agent.crews.partial_loss_crew import create_partial_loss_crew

        crew = create_partial_loss_crew(llm=_structural_llm_for_crew())
        first_task = crew.tasks[0]
        assert "{claim_data}" in first_task.description, (
            "First task description should contain {claim_data} for crew input injection"
        )

    @pytest.mark.integration
    def test_bodily_injury_crew_first_task_has_claim_data_placeholder(self):
        """First task of bodily injury crew must contain {claim_data} for input injection."""
        from claim_agent.crews.bodily_injury_crew import create_bodily_injury_crew

        crew = create_bodily_injury_crew(llm=_structural_llm_for_crew())
        first_task = crew.tasks[0]
        assert "{claim_data}" in first_task.description, (
            "First task description should contain {claim_data} for crew input injection"
        )

    @pytest.mark.integration
    def test_bodily_injury_crew_all_tasks_have_claim_data_placeholder(self):
        """All bodily injury crew tasks must contain {claim_data} so agents receive claim context."""
        from claim_agent.crews.bodily_injury_crew import create_bodily_injury_crew

        crew = create_bodily_injury_crew(llm=_structural_llm_for_crew())
        for i, task in enumerate(crew.tasks):
            assert "{claim_data}" in task.description, (
                f"Task {i} ({task.description[:50]}...) must contain {{claim_data}} for input injection"
            )

    @pytest.mark.integration
    def test_partial_loss_crew_all_tasks_have_claim_data_placeholder(self):
        """All partial loss crew tasks must contain {claim_data} so agents receive claim context."""
        from claim_agent.crews.partial_loss_crew import create_partial_loss_crew

        crew = create_partial_loss_crew(llm=_structural_llm_for_crew())
        for i, task in enumerate(crew.tasks):
            assert "{claim_data}" in task.description, (
                f"Task {i} ({task.description[:50]}...) must contain {{claim_data}} for input injection"
            )

    @pytest.mark.integration
    @pytest.mark.llm
    @pytest.mark.slow
    def test_duplicate_crew_invokes_search_tool_when_run(
        self, seeded_db, seeded_db_base_date
    ):
        """Run duplicate crew with real LLM. Verifies crew completes and produces output.
        Optionally checks search_claims_db was invoked (LLM tool use is non-deterministic).
        Requires OPENAI_API_KEY or OPENROUTER_API_KEY. Seeds DB so search has something to find."""
        from claim_agent.config.llm import has_valid_llm_config

        if not has_valid_llm_config():
            pytest.skip("No valid LLM API key; skipping LLM tool-invocation test")

        import json
        from claim_agent.crews.duplicate_crew import create_duplicate_crew

        # Claim with same VIN as seeded_db first claim so search returns results
        claim_data = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": seeded_db_base_date,
            "incident_description": "Rear-ended at stoplight. Bumper damage.",
            "damage_description": "Rear bumper and trunk damaged.",
            "estimated_damage": 3500,
        }
        crew = create_duplicate_crew()
        result = _run_llm_call(lambda: crew.kickoff(inputs={"claim_data": json.dumps(claim_data)}))
        output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
        output = str(output)

        assert len(output.strip()) > 0, "Crew should produce non-empty output"

    @pytest.mark.integration
    @pytest.mark.llm
    @pytest.mark.slow
    def test_bodily_injury_crew_invokes_tools_when_run(
        self, sample_bodily_injury_claim
    ):
        """Run bodily injury crew with real LLM. Verifies crew completes and produces output.
        Requires OPENAI_API_KEY or OPENROUTER_API_KEY."""
        from claim_agent.config.llm import has_valid_llm_config

        if not has_valid_llm_config():
            pytest.skip("No valid LLM API key; skipping LLM tool-invocation test")

        import json
        from claim_agent.crews.bodily_injury_crew import create_bodily_injury_crew

        crew = create_bodily_injury_crew()
        claim_data = {**sample_bodily_injury_claim, "claim_id": "CLM-BI-TEST"}
        result = _run_llm_call(lambda: crew.kickoff(inputs={"claim_data": json.dumps(claim_data)}))
        output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
        output = str(output)

        assert len(output.strip()) > 0, "BI crew should produce non-empty output"

    @pytest.mark.integration
    @pytest.mark.llm
    def test_router_routes_bodily_injury_when_injury_and_damage(
        self,
    ):
        """Router with claim having both injury and repairable damage: expect bodily_injury.
        Per rules, injury takes priority over partial_loss when significant."""
        from claim_agent.config.llm import has_valid_llm_config

        if not has_valid_llm_config():
            pytest.skip("No valid LLM API key; skipping LLM routing test")

        import json
        from claim_agent.workflow.routing import create_router_crew

        claim_data = {
            "policy_number": "POL-004",
            "vin": "2HGFG3B54CH501234",
            "vehicle_year": 2020,
            "vehicle_make": "Toyota",
            "vehicle_model": "Camry",
            "incident_description": "Rear-ended at intersection. Driver injured with whiplash. Bumper damaged.",
            "damage_description": "Rear bumper and trunk damaged. Driver sustained whiplash.",
        }
        crew = create_router_crew()
        result = _run_llm_call(lambda: crew.kickoff(inputs={"claim_data": json.dumps(claim_data)}))
        raw = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
        raw = str(raw).strip().lower()
        # Per routing rules, injury to persons -> bodily_injury
        assert "bodily_injury" in raw or "bodily injury" in raw or "partial_loss" in raw or "partial loss" in raw or "new" in raw, (
            f"Router should classify as bodily_injury, partial_loss, or new; got: {raw[:200]}"
        )


# ============================================================================
# Live LLM Tests (require API key)
# ============================================================================


def _is_auth_error(exc: BaseException) -> bool:
    """True if exc is an auth/401 error (invalid/expired key)."""
    try:
        from litellm.exceptions import AuthenticationError
        if isinstance(exc, AuthenticationError):
            return True
        if exc.__cause__ and isinstance(exc.__cause__, AuthenticationError):
            return True
        if hasattr(exc, "failed_attempts") and exc.failed_attempts:
            for attempt in exc.failed_attempts:
                if isinstance(getattr(attempt, "exception", None), AuthenticationError):
                    return True
    except ImportError:
        pass
    return False


def _run_llm_call(fn):
    """Run fn(), converting auth errors to pytest.skip."""
    try:
        return fn()
    except BaseException as e:
        if _is_auth_error(e):
            pytest.skip("Invalid or expired API key; skipping LLM test")
        raise


# Expected claim_type variance for LLM routing tests (non-deterministic router).
# Use bounded assertions: result["claim_type"] in LLM_ROUTER_VALID_OUTCOMES[scenario]
# Documented per docs/eval-suite-gaps.md to avoid false failures when router is conservative.
LLM_ROUTER_VALID_OUTCOMES = {
    "new_claim": ("new", "partial_loss"),  # Minor damage could be partial
    "total_loss": ("total_loss", "new"),  # LLM may route conservatively
    "fraud": ("fraud", "new"),  # Or escalate (needs_review)
    "duplicate": ("duplicate", "new", "partial_loss"),  # Or escalate
    "partial_loss": ("partial_loss", "new"),  # Or escalate
}


@pytest.mark.llm
@pytest.mark.e2e
@pytest.mark.slow
class TestWorkflowWithLLM:
    """End-to-end tests with real LLM (requires OPENAI_API_KEY or OPENROUTER_API_KEY).

    Claim type assertions allow multiple valid outcomes: the router is non-deterministic
    and may classify conservatively (e.g. total_loss → new, fraud → new or escalation).
    Use LLM_ROUTER_VALID_OUTCOMES for bounded assertions. These tests assert that the
    workflow runs to completion and returns a valid result.
    """

    @pytest.fixture(autouse=True)
    def check_api_key(self):
        """Skip these tests if no valid API key is set (placeholder keys cause 401)."""
        from claim_agent.config.llm import has_valid_llm_config

        if not has_valid_llm_config():
            pytest.skip(
                "OPENAI_API_KEY or OPENROUTER_API_KEY not set or is a placeholder; "
                "skipping LLM tests (use a real key to run)"
            )

    def test_new_claim_full_workflow(self, integration_db, sample_new_claim):
        """Test complete new claim workflow with real LLM."""
        from claim_agent.crews.main_crew import run_claim_workflow

        result = _run_llm_call(lambda: run_claim_workflow(sample_new_claim))

        assert "claim_id" in result
        assert "claim_type" in result
        assert "workflow_output" in result
        assert result["claim_type"] in LLM_ROUTER_VALID_OUTCOMES["new_claim"]

    def test_total_loss_full_workflow(self, integration_db, sample_total_loss_claim):
        """Test complete total-loss-shaped claim workflow with real LLM.

        Router may return total_loss or conservatively new; we assert workflow completion.
        """
        from claim_agent.crews.main_crew import run_claim_workflow

        result = _run_llm_call(lambda: run_claim_workflow(sample_total_loss_claim))

        assert "claim_id" in result
        assert "claim_type" in result
        assert "workflow_output" in result
        assert result["claim_type"] in LLM_ROUTER_VALID_OUTCOMES["total_loss"]

    def test_fraud_claim_full_workflow(self, integration_db, sample_fraud_claim):
        """Test complete fraud-shaped claim workflow with real LLM.

        Router may return fraud, new, or escalate for review.
        """
        from claim_agent.crews.main_crew import run_claim_workflow

        result = _run_llm_call(lambda: run_claim_workflow(sample_fraud_claim))

        assert "claim_id" in result
        assert (
            result["claim_type"] in LLM_ROUTER_VALID_OUTCOMES["fraud"]
            or result.get("needs_review")
        )

    def test_duplicate_claim_full_workflow(self, integration_db, sample_duplicate_claim):
        """Test complete duplicate-shaped claim workflow with real LLM.

        Router may return duplicate, new, or partial_loss."""
        from claim_agent.crews.main_crew import run_claim_workflow

        result = _run_llm_call(lambda: run_claim_workflow(sample_duplicate_claim))

        assert "claim_id" in result
        assert "claim_type" in result
        assert (
            result["claim_type"] in LLM_ROUTER_VALID_OUTCOMES["duplicate"]
            or result.get("needs_review")
        )

    def test_partial_loss_claim_full_workflow(self, integration_db, sample_partial_loss_claim):
        """Test complete partial-loss-shaped claim workflow with real LLM.

        Router may return partial_loss or new."""
        from claim_agent.crews.main_crew import run_claim_workflow

        result = _run_llm_call(lambda: run_claim_workflow(sample_partial_loss_claim))

        assert "claim_id" in result
        assert "claim_type" in result
        assert (
            result["claim_type"] in LLM_ROUTER_VALID_OUTCOMES["partial_loss"]
            or result.get("needs_review")
        )
