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
from claim_agent.models.workflow_output import PartialLossWorkflowOutput, TotalLossWorkflowOutput


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
):
    """Submit new claim via POST /api/claims; assert claim_id, status, history."""
    factory_mod._storage_instance = None
    with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
        with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
            with patch("claim_agent.crews.main_crew.create_new_claim_crew") as mock_crew:
                with patch("claim_agent.crews.main_crew.evaluate_escalation_impl") as mock_esc:
                    mock_llm.return_value = MagicMock()
                    mock_router.return_value.kickoff.return_value = mock_router_response("new")
                    mock_crew.return_value.kickoff.return_value = mock_crew_response(
                        "Claim processed successfully."
                    )
                    mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'

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
):
    """Submit duplicate claim via POST /api/claims; assert claim_id, status, history."""
    factory_mod._storage_instance = None
    with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
        with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
            with patch("claim_agent.crews.main_crew.create_duplicate_crew") as mock_crew:
                with patch("claim_agent.crews.main_crew.evaluate_escalation_impl") as mock_esc:
                    mock_llm.return_value = MagicMock()
                    mock_router.return_value.kickoff.return_value = mock_router_response(
                        "duplicate", "Matches existing claim."
                    )
                    mock_crew.return_value.kickoff.return_value = mock_crew_response(
                        "Duplicate confirmed. Original claim: CLM-001."
                    )
                    mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'

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
    with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
        with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
            with patch("claim_agent.crews.main_crew.create_total_loss_crew") as mock_crew:
                with patch("claim_agent.crews.main_crew.create_settlement_crew") as mock_settlement:
                    with patch("claim_agent.crews.main_crew.evaluate_escalation_impl") as mock_esc:
                        mock_llm.return_value = MagicMock()
                        mock_router.return_value.kickoff.return_value = mock_router_response(
                            "total_loss", "Vehicle flooded - total destruction."
                        )
                        mock_crew.return_value.kickoff.return_value = mock_crew_response(
                            "Total loss confirmed.",
                            tasks_output=workflow_tasks_output,
                        )
                        mock_settlement.return_value.kickoff.return_value = mock_crew_response(
                            "Settlement completed."
                        )
                        mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'

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
):
    """Submit fraud claim via POST /api/claims; assert claim_id, status, history."""
    factory_mod._storage_instance = None
    with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
        with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
            with patch("claim_agent.crews.main_crew.create_fraud_detection_crew") as mock_crew:
                with patch("claim_agent.crews.main_crew.evaluate_escalation_impl") as mock_esc:
                    mock_llm.return_value = MagicMock()
                    mock_router.return_value.kickoff.return_value = mock_router_response(
                        "fraud", "Suspicious indicators."
                    )
                    mock_crew.return_value.kickoff.return_value = mock_crew_response(
                        "Fraud indicators detected."
                    )
                    mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'

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
    with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
        with patch("claim_agent.crews.main_crew.create_router_crew") as mock_router:
            with patch("claim_agent.crews.main_crew.create_partial_loss_crew") as mock_partial:
                with patch("claim_agent.crews.main_crew.create_settlement_crew") as mock_settlement:
                    with patch("claim_agent.crews.main_crew.evaluate_escalation_impl") as mock_esc:
                        mock_llm.return_value = MagicMock()
                        mock_router.return_value.kickoff.return_value = mock_router_response(
                            "partial_loss", "Repairable fender damage."
                        )
                        mock_partial.return_value.kickoff.return_value = mock_crew_response(
                            "Repair authorization created.",
                            tasks_output=workflow_tasks_output,
                        )
                        mock_settlement.return_value.kickoff.return_value = mock_crew_response(
                            "Settlement completed."
                        )
                        mock_esc.return_value = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'

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
