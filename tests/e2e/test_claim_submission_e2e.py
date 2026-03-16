"""E2E tests: submit claims via REST API and assert outcomes.

Tests use mocked LLM (no API key required for CI).
"""

from unittest.mock import MagicMock, patch

import pytest

import claim_agent.storage.factory as factory_mod
from claim_agent.db.constants import (
    STATUS_DUPLICATE,
    STATUS_FRAUD_SUSPECTED,
    STATUS_OPEN,
    STATUS_SETTLED,
)
from claim_agent.models.workflow_output import (
    BIWorkflowOutput,
    PartialLossWorkflowOutput,
    TotalLossWorkflowOutput,
)


# ============================================================================
# E2E: New claim
# ============================================================================


@pytest.mark.e2e
def test_e2e_submit_new_claim_via_api(
    e2e_client,
    integration_db,
    sample_new_claim,
    mock_router_response,
    mock_crew_response,
    mock_llm_instance,
):
    """Submit new claim via POST /api/claims; assert claim_id, status, history."""
    factory_mod._storage_instance = None
    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.create_new_claim_crew") as mock_crew:
                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                        with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                            with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                                mock_llm.return_value = mock_llm_instance
                                mock_router.return_value.kickoff.return_value = mock_router_response("new")
                                mock_crew.return_value.kickoff.return_value = mock_crew_response(
                                    "Claim processed successfully."
                                )
                                mock_after.return_value.kickoff.return_value = mock_crew_response(
                                    "After-action summary added."
                                )
                                mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                    "Tasks created."
                                )

                                resp = e2e_client.post("/api/claims", json=sample_new_claim)

    assert resp.status_code == 200
    data = resp.json()
    assert "claim_id" in data
    assert data["claim_id"].startswith("CLM-")
    assert data.get("status") == STATUS_OPEN
    assert data.get("claim_type") == "new"

    history_resp = e2e_client.get(f"/api/claims/{data['claim_id']}/history")
    assert history_resp.status_code == 200
    history = history_resp.json()["history"]
    assert len(history) >= 2
    actions = [h["action"] for h in history]
    assert "created" in actions
    assert "status_change" in actions


# ============================================================================
# E2E: Duplicate claim
# ============================================================================


@pytest.mark.e2e
def test_e2e_submit_duplicate_claim_via_api(
    e2e_client,
    integration_db,
    sample_duplicate_claim,
    mock_router_response,
    mock_crew_response,
    mock_llm_instance,
):
    """Submit duplicate claim via POST /api/claims; assert claim_id, status, history."""
    factory_mod._storage_instance = None
    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.create_duplicate_crew") as mock_crew:
                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                        with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                            with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                                mock_llm.return_value = mock_llm_instance
                                mock_router.return_value.kickoff.return_value = mock_router_response(
                                    "duplicate", "Matches existing claim."
                                )
                                mock_crew.return_value.kickoff.return_value = mock_crew_response(
                                    "Duplicate confirmed. Original claim: CLM-001."
                                )
                                mock_after.return_value.kickoff.return_value = mock_crew_response(
                                    "After-action summary added."
                                )
                                mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                    "Tasks created."
                                )

                                resp = e2e_client.post("/api/claims", json=sample_duplicate_claim)

    assert resp.status_code == 200
    data = resp.json()
    assert "claim_id" in data
    assert data["claim_id"].startswith("CLM-")
    assert data.get("status") == STATUS_DUPLICATE
    assert data.get("claim_type") == "duplicate"

    history_resp = e2e_client.get(f"/api/claims/{data['claim_id']}/history")
    assert history_resp.status_code == 200
    history = history_resp.json()["history"]
    assert len(history) >= 2


# ============================================================================
# E2E: Total loss claim
# ============================================================================


@pytest.mark.e2e
def test_e2e_submit_total_loss_claim_via_api(
    e2e_client,
    integration_db,
    sample_total_loss_claim,
    mock_router_response,
    mock_crew_response,
    mock_llm_instance,
):
    """Submit total loss claim via POST /api/claims; assert claim_id, status, history."""
    # Low damage to avoid escalation
    low_value_claim = {**sample_total_loss_claim, "estimated_damage": 5000}

    mock_task = MagicMock()
    mock_task.output = TotalLossWorkflowOutput(
        payout_amount=14500.0,
        vehicle_value=15000.0,
        deductible=500.0,
        calculation="15000 - 500",
    )
    workflow_tasks_output = [MagicMock(), MagicMock(), mock_task]

    factory_mod._storage_instance = None
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
                                                "Total loss confirmed.",
                                                tasks_output=workflow_tasks_output,
                                            )
                                            mock_liability.return_value.kickoff.return_value = mock_crew_response(
                                                "Liability determination: not at fault."
                                            )
                                            mock_settlement.return_value.kickoff.return_value = mock_crew_response(
                                                "Settlement completed."
                                            )
                                            mock_subrogation.return_value.kickoff.return_value = mock_crew_response(
                                                "Subrogation assessment complete. No recovery opportunity."
                                            )
                                            mock_salvage.return_value.kickoff.return_value = mock_crew_response(
                                                "Salvage disposition complete."
                                            )
                                            mock_after.return_value.kickoff.return_value = mock_crew_response(
                                                "After-action summary added."
                                            )
                                            mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                            mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                                "Tasks created."
                                            )

                                            resp = e2e_client.post("/api/claims", json=low_value_claim)

    assert resp.status_code == 200
    data = resp.json()
    assert "claim_id" in data
    assert data["claim_id"].startswith("CLM-")
    assert data.get("status") == STATUS_SETTLED
    assert data.get("claim_type") == "total_loss"

    history_resp = e2e_client.get(f"/api/claims/{data['claim_id']}/history")
    assert history_resp.status_code == 200
    history = history_resp.json()["history"]
    assert len(history) >= 2


# ============================================================================
# E2E: Fraud claim
# ============================================================================


@pytest.mark.e2e
def test_e2e_submit_fraud_claim_via_api(
    e2e_client,
    integration_db,
    sample_fraud_claim,
    mock_router_response,
    mock_crew_response,
    mock_llm_instance,
):
    """Submit fraud claim via POST /api/claims; assert claim_id, status, history."""
    factory_mod._storage_instance = None
    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.create_fraud_detection_crew") as mock_crew:
                    with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                        with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                            with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                                mock_llm.return_value = mock_llm_instance
                                mock_router.return_value.kickoff.return_value = mock_router_response(
                                    "fraud", "Suspicious indicators."
                                )
                                mock_crew.return_value.kickoff.return_value = mock_crew_response(
                                    "Fraud indicators detected."
                                )
                                mock_after.return_value.kickoff.return_value = mock_crew_response(
                                    "After-action summary added."
                                )
                                mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                    "Tasks created."
                                )

                                resp = e2e_client.post("/api/claims", json=sample_fraud_claim)

    assert resp.status_code == 200
    data = resp.json()
    assert "claim_id" in data
    assert data["claim_id"].startswith("CLM-")
    assert data.get("status") == STATUS_FRAUD_SUSPECTED
    assert data.get("claim_type") == "fraud"

    history_resp = e2e_client.get(f"/api/claims/{data['claim_id']}/history")
    assert history_resp.status_code == 200
    history = history_resp.json()["history"]
    assert len(history) >= 2


# ============================================================================
# E2E: Partial loss claim
# ============================================================================


@pytest.mark.e2e
def test_e2e_submit_partial_loss_claim_via_api(
    e2e_client,
    integration_db,
    sample_partial_loss_claim,
    mock_router_response,
    mock_crew_response,
    mock_llm_instance,
):
    """Submit partial loss claim via POST /api/claims; assert claim_id, status, history."""
    mock_task = MagicMock()
    mock_task.output = PartialLossWorkflowOutput(
        payout_amount=2100.0,
        authorization_id="AUTH-001",
        total_estimate=2500.0,
    )
    workflow_tasks_output = [mock_task]

    factory_mod._storage_instance = None
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
                                                "Repair authorization created.",
                                                tasks_output=workflow_tasks_output,
                                            )
                                            mock_rental.return_value.kickoff.return_value = mock_crew_response(
                                                "Rental eligibility confirmed. Reimbursement processed."
                                            )
                                            mock_liability.return_value.kickoff.return_value = mock_crew_response(
                                                "Liability determination: not at fault."
                                            )
                                            mock_settlement.return_value.kickoff.return_value = mock_crew_response(
                                                "Settlement completed."
                                            )
                                            mock_subrogation.return_value.kickoff.return_value = mock_crew_response(
                                                "Subrogation assessment complete. No recovery opportunity."
                                            )
                                            mock_after.return_value.kickoff.return_value = mock_crew_response(
                                                "After-action summary added."
                                            )
                                            mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                            mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                                "Tasks created."
                                            )

                                            resp = e2e_client.post("/api/claims", json=sample_partial_loss_claim)

    assert resp.status_code == 200
    data = resp.json()
    assert "claim_id" in data
    assert data["claim_id"].startswith("CLM-")
    assert data.get("status") == STATUS_SETTLED
    assert data.get("claim_type") == "partial_loss"

    history_resp = e2e_client.get(f"/api/claims/{data['claim_id']}/history")
    assert history_resp.status_code == 200
    history = history_resp.json()["history"]
    assert len(history) >= 2


# ============================================================================
# E2E: Bodily injury claim
# ============================================================================


@pytest.mark.e2e
def test_e2e_submit_bodily_injury_claim_via_api(
    e2e_client,
    integration_db,
    sample_bodily_injury_claim,
    mock_router_response,
    mock_crew_response,
    mock_llm_instance,
):
    """Submit bodily injury claim via POST /api/claims; assert claim_id, status, history."""
    mock_task = MagicMock()
    mock_task.output = BIWorkflowOutput(
        payout_amount=8500.0,
        medical_charges=3750.0,
        pain_suffering=5625.0,
        injury_severity="moderate",
        policy_bi_limit_per_person=250000.0,
        policy_bi_limit_per_accident=500000.0,
    )
    workflow_tasks_output = [mock_task]

    factory_mod._storage_instance = None
    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.create_bodily_injury_crew") as mock_bi_crew:
                with patch("claim_agent.workflow.stages.create_liability_determination_crew") as mock_liability:
                    with patch("claim_agent.workflow.stages.create_settlement_crew") as mock_settlement:
                        with patch("claim_agent.workflow.stages.create_subrogation_crew") as mock_subrogation:
                            with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                                with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                                    with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                                        mock_llm.return_value = mock_llm_instance
                                        mock_router.return_value.kickoff.return_value = mock_router_response(
                                            "bodily_injury", "Passenger injured in collision."
                                        )
                                        mock_bi_crew.return_value.kickoff.return_value = mock_crew_response(
                                            "BI settlement proposed.",
                                            tasks_output=workflow_tasks_output,
                                        )
                                        mock_liability.return_value.kickoff.return_value = mock_crew_response(
                                            "Liability determination: not at fault."
                                        )
                                        mock_settlement.return_value.kickoff.return_value = mock_crew_response(
                                            "Settlement completed."
                                        )
                                        mock_subrogation.return_value.kickoff.return_value = mock_crew_response(
                                            "Subrogation assessment complete. No recovery opportunity."
                                        )
                                        mock_after.return_value.kickoff.return_value = mock_crew_response(
                                            "After-action summary added."
                                        )
                                        mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'
                                        mock_task_planner.return_value.kickoff.return_value = mock_crew_response(
                                            "Tasks created."
                                        )

                                        resp = e2e_client.post("/api/claims", json=sample_bodily_injury_claim)

    assert resp.status_code == 200
    data = resp.json()
    assert "claim_id" in data
    assert data["claim_id"].startswith("CLM-")
    assert data.get("status") == STATUS_SETTLED
    assert data.get("claim_type") == "bodily_injury"

    history_resp = e2e_client.get(f"/api/claims/{data['claim_id']}/history")
    assert history_resp.status_code == 200
    history = history_resp.json()["history"]
    assert len(history) >= 2
