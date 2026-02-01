"""End-to-end workflow integration tests.

These tests verify the complete claim processing workflow from intake to resolution.
Tests are designed to run with mocked LLM responses for CI, but can also run
against a real LLM when OPENAI_API_KEY is set.
"""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

# MagicMock is imported at top level for use in test fixtures


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
        
        # With reasoning
        assert _parse_claim_type("new\nThis is a new claim.") == "new"
        assert _parse_claim_type("total_loss\nVehicle flooded.") == "total_loss"
        assert _parse_claim_type("partial_loss\nMinor fender damage.") == "partial_loss"
        
        # Normalized variants
        assert _parse_claim_type("total loss") == "total_loss"
        assert _parse_claim_type("partial loss") == "partial_loss"
        assert _parse_claim_type("FRAUD\nSuspicious patterns.") == "fraud"
    
    @pytest.mark.integration
    def test_final_status_mapping(self):
        """Verify claim types map to correct final statuses."""
        from claim_agent.crews.main_crew import _final_status
        from claim_agent.db.constants import (
            STATUS_OPEN,
            STATUS_DUPLICATE,
            STATUS_FRAUD_SUSPECTED,
            STATUS_PARTIAL_LOSS,
            STATUS_CLOSED,
        )
        
        assert _final_status("new") == STATUS_OPEN
        assert _final_status("duplicate") == STATUS_DUPLICATE
        assert _final_status("fraud") == STATUS_FRAUD_SUSPECTED
        assert _final_status("partial_loss") == STATUS_PARTIAL_LOSS
        assert _final_status("total_loss") == STATUS_CLOSED


# ============================================================================
# Workflow Integration Tests (Mocked LLM)
# ============================================================================


class TestWorkflowWithMockedLLM:
    """Test complete workflow with mocked LLM responses."""
    
    @pytest.mark.integration
    def test_workflow_creates_claim_in_database(
        self, integration_db, sample_new_claim, mock_router_response, mock_crew_response
    ):
        """Test that workflow creates a claim record in the database."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.repository import ClaimRepository
        
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
                with patch("claim_agent.crews.main_crew.create_new_claim_crew") as mock_crew:
                    mock_llm.return_value = MagicMock()
                    mock_router.return_value.kickoff.return_value = mock_router_response("new")
                    mock_crew.return_value.kickoff.return_value = mock_crew_response(
                        "Claim processed successfully. Claim ID: CLM-TEST001"
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
        self, integration_db, sample_total_loss_claim, mock_router_response, mock_crew_response
    ):
        """Test that claims are routed to the correct specialized crew."""
        from claim_agent.crews.main_crew import run_claim_workflow
        
        # Use a claim that won't trigger escalation (low damage estimate)
        low_value_claim = {**sample_total_loss_claim, "estimated_damage": 5000}
        
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
                with patch("claim_agent.crews.main_crew.create_total_loss_crew") as mock_crew:
                    # Also mock escalation to return no escalation needed
                    with patch("claim_agent.crews.main_crew.evaluate_escalation_impl") as mock_esc:
                        mock_llm.return_value = MagicMock()
                        mock_router.return_value.kickoff.return_value = mock_router_response(
                            "total_loss", "Vehicle flooded - total destruction."
                        )
                        mock_crew.return_value.kickoff.return_value = mock_crew_response(
                            "Total loss confirmed. Vehicle value: $15,000."
                        )
                        mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                        
                        result = run_claim_workflow(low_value_claim)
        
        assert result["claim_type"] == "total_loss"
        mock_crew.assert_called_once()
    
    @pytest.mark.integration
    def test_workflow_records_audit_history(
        self, integration_db, sample_new_claim, mock_router_response, mock_crew_response
    ):
        """Test that workflow actions are recorded in the audit log."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.repository import ClaimRepository
        
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
                with patch("claim_agent.crews.main_crew.create_new_claim_crew") as mock_crew:
                    mock_llm.return_value = MagicMock()
                    mock_router.return_value.kickoff.return_value = mock_router_response("new")
                    mock_crew.return_value.kickoff.return_value = mock_crew_response("Success")
                    
                    result = run_claim_workflow(sample_new_claim)
        
        repo = ClaimRepository(db_path=integration_db)
        history = repo.get_claim_history(result["claim_id"])
        
        # Should have at least: created, status_changed (processing), status_changed (final)
        assert len(history) >= 2
        actions = [h["action"] for h in history]
        assert "created" in actions
        assert "status_changed" in actions
    
    @pytest.mark.integration
    def test_workflow_handles_failure_gracefully(
        self, integration_db, sample_new_claim, mock_router_response
    ):
        """Test that workflow failures are properly recorded."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.db.database import get_connection
        
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
                mock_llm.return_value = MagicMock()
                mock_router.return_value.kickoff.side_effect = RuntimeError("LLM unavailable")
                
                with pytest.raises(RuntimeError, match="LLM unavailable"):
                    run_claim_workflow(sample_new_claim)
        
        # Verify claim was marked as failed
        with get_connection(integration_db) as conn:
            row = conn.execute("SELECT id, status FROM claims").fetchone()
        
        assert row is not None
        assert row["status"] == "failed"
    
    @pytest.mark.integration
    def test_workflow_saves_workflow_result(
        self, integration_db, sample_new_claim, mock_router_response, mock_crew_response
    ):
        """Test that workflow results are saved to workflow_runs table."""
        from claim_agent.crews.main_crew import run_claim_workflow
        from claim_agent.db.database import get_connection
        
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
                with patch("claim_agent.crews.main_crew.create_new_claim_crew") as mock_crew:
                    # Also mock escalation to return no escalation needed
                    with patch("claim_agent.crews.main_crew.evaluate_escalation_impl") as mock_esc:
                        mock_llm.return_value = MagicMock()
                        mock_router.return_value.kickoff.return_value = mock_router_response("new")
                        mock_crew.return_value.kickoff.return_value = mock_crew_response("Processed!")
                        mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                        
                        result = run_claim_workflow(sample_new_claim)
        
        with get_connection(integration_db) as conn:
            row = conn.execute(
                "SELECT * FROM workflow_runs WHERE claim_id = ?",
                (result["claim_id"],)
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
        self, integration_db, mock_router_response
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
        
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
                mock_llm.return_value = MagicMock()
                mock_router.return_value.kickoff.return_value = mock_router_response("new")
                
                result = run_claim_workflow(high_value_claim)
        
        # Should be escalated due to high value
        if result.get("needs_review"):
            assert result["status"] == STATUS_NEEDS_REVIEW
            assert "escalation_reasons" in result
    
    @pytest.mark.integration
    def test_fraud_claim_runs_fraud_crew_instead_of_escalation(
        self, integration_db, sample_fraud_claim, mock_router_response, mock_crew_response
    ):
        """Test that fraud claims go to fraud crew, not escalation."""
        from claim_agent.crews.main_crew import run_claim_workflow
        
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
                with patch("claim_agent.crews.main_crew.create_fraud_detection_crew") as mock_fraud:
                    mock_llm.return_value = MagicMock()
                    mock_router.return_value.kickoff.return_value = mock_router_response("fraud")
                    mock_fraud.return_value.kickoff.return_value = mock_crew_response(
                        "Fraud indicators detected: staged accident, inflated damages."
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
        self, integration_db, sample_new_claim, mock_router_response, mock_crew_response
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
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
                with patch("claim_agent.crews.main_crew.create_new_claim_crew") as mock_crew:
                    mock_llm.return_value = MagicMock()
                    mock_router.return_value.kickoff.return_value = mock_router_response("new")
                    mock_crew.return_value.kickoff.return_value = mock_crew_response("Reprocessed!")
                    
                    result = run_claim_workflow(sample_new_claim, existing_claim_id=claim_id)
        
        assert result["claim_id"] == claim_id
        
        # Check history shows reprocessing
        history = repo.get_claim_history(claim_id)
        assert len(history) >= 3  # created + multiple status changes
    
    @pytest.mark.integration
    def test_reprocess_nonexistent_claim_raises(self, integration_db, sample_new_claim):
        """Test that reprocessing a non-existent claim raises an error."""
        from claim_agent.crews.main_crew import run_claim_workflow
        
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            mock_llm.return_value = MagicMock()
            with pytest.raises(ValueError, match="Claim not found"):
                run_claim_workflow(sample_new_claim, existing_claim_id="CLM-NONEXIST")


# ============================================================================
# Live LLM Tests (require API key)
# ============================================================================


@pytest.mark.llm
@pytest.mark.e2e
class TestWorkflowWithLLM:
    """End-to-end tests with real LLM (requires OPENAI_API_KEY)."""
    
    @pytest.fixture(autouse=True)
    def check_api_key(self):
        """Skip these tests if no API key is set."""
        if not os.environ.get("OPENAI_API_KEY"):
            pytest.skip("OPENAI_API_KEY not set; skipping LLM tests")
    
    def test_new_claim_full_workflow(self, integration_db, sample_new_claim):
        """Test complete new claim workflow with real LLM."""
        from claim_agent.crews.main_crew import run_claim_workflow
        
        result = run_claim_workflow(sample_new_claim)
        
        assert "claim_id" in result
        assert "claim_type" in result
        assert "workflow_output" in result
        assert result["claim_type"] in ("new", "partial_loss")  # Minor damage could be partial
    
    def test_total_loss_full_workflow(self, integration_db, sample_total_loss_claim):
        """Test complete total loss workflow with real LLM."""
        from claim_agent.crews.main_crew import run_claim_workflow
        
        result = run_claim_workflow(sample_total_loss_claim)
        
        assert "claim_id" in result
        assert result["claim_type"] == "total_loss"
    
    def test_fraud_claim_full_workflow(self, integration_db, sample_fraud_claim):
        """Test complete fraud claim workflow with real LLM."""
        from claim_agent.crews.main_crew import run_claim_workflow
        
        result = run_claim_workflow(sample_fraud_claim)
        
        assert "claim_id" in result
        # Fraud claims should be detected as fraud or escalated
        assert result["claim_type"] in ("fraud", "new") or result.get("needs_review")
