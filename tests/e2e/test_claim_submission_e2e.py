"""E2E tests: submit claims via REST API and assert outcomes.

Tests use mocked LLM (no API key required for CI).
"""

from unittest.mock import MagicMock

import pytest

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

_STAGES = "claim_agent.workflow.stages"


# ============================================================================
# E2E: New claim
# ============================================================================


@pytest.mark.e2e
def test_e2e_submit_new_claim_via_api(
    e2e_client,
    integration_db,
    sample_new_claim,
    mock_crew_response,
    workflow_patches,
):
    """Submit new claim via POST /api/claims; assert claim_id, status, history."""
    with workflow_patches as mocks:
        mocks.set_router("new")
        crew = mocks.add_patch(f"{_STAGES}.create_new_claim_crew")
        crew.return_value.kickoff.return_value = mock_crew_response(
            "Claim processed successfully."
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
    mock_crew_response,
    workflow_patches,
):
    """Submit duplicate claim via POST /api/claims; assert claim_id, status, history."""
    with workflow_patches as mocks:
        mocks.set_router("duplicate", "Matches existing claim.")
        crew = mocks.add_patch(f"{_STAGES}.create_duplicate_crew")
        crew.return_value.kickoff.return_value = mock_crew_response(
            "Duplicate confirmed. Original claim: CLM-001."
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
    mock_crew_response,
    workflow_patches,
):
    """Submit total loss claim via POST /api/claims; assert claim_id, status, history."""
    low_value_claim = {**sample_total_loss_claim, "estimated_damage": 5000}

    mock_task = MagicMock()
    mock_task.output = TotalLossWorkflowOutput(
        payout_amount=14500.0,
        vehicle_value=15000.0,
        deductible=500.0,
        calculation="15000 - 500",
    )
    workflow_tasks_output = [MagicMock(), MagicMock(), mock_task]

    with workflow_patches as mocks:
        mocks.set_router("total_loss", "Vehicle flooded - total destruction.")

        crew = mocks.add_patch(f"{_STAGES}.create_total_loss_crew")
        crew.return_value.kickoff.return_value = mock_crew_response(
            "Total loss confirmed.", tasks_output=workflow_tasks_output,
        )

        liability = mocks.add_patch(f"{_STAGES}.create_liability_determination_crew")
        liability.return_value.kickoff.return_value = mock_crew_response(
            "Liability determination: not at fault."
        )

        settlement = mocks.add_patch(f"{_STAGES}.create_settlement_crew")
        settlement.return_value.kickoff.return_value = mock_crew_response(
            "Settlement completed."
        )

        subrogation = mocks.add_patch(f"{_STAGES}.create_subrogation_crew")
        subrogation.return_value.kickoff.return_value = mock_crew_response(
            "Subrogation assessment complete. No recovery opportunity."
        )

        salvage = mocks.add_patch(f"{_STAGES}.create_salvage_crew")
        salvage.return_value.kickoff.return_value = mock_crew_response(
            "Salvage disposition complete."
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
    mock_crew_response,
    workflow_patches,
):
    """Submit fraud claim via POST /api/claims; assert claim_id, status, history."""
    with workflow_patches as mocks:
        mocks.set_router("fraud", "Suspicious indicators.")
        crew = mocks.add_patch(f"{_STAGES}.create_fraud_detection_crew")
        crew.return_value.kickoff.return_value = mock_crew_response(
            "Fraud indicators detected."
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
    mock_crew_response,
    workflow_patches,
):
    """Submit partial loss claim via POST /api/claims; assert claim_id, status, history."""
    mock_task = MagicMock()
    mock_task.output = PartialLossWorkflowOutput(
        payout_amount=2100.0,
        authorization_id="AUTH-001",
        total_estimate=2500.0,
    )
    workflow_tasks_output = [mock_task]

    with workflow_patches as mocks:
        mocks.set_router("partial_loss", "Repairable fender damage.")

        partial = mocks.add_patch(f"{_STAGES}.create_partial_loss_crew")
        partial.return_value.kickoff.return_value = mock_crew_response(
            "Repair authorization created.", tasks_output=workflow_tasks_output,
        )

        rental = mocks.add_patch(f"{_STAGES}.create_rental_crew")
        rental.return_value.kickoff.return_value = mock_crew_response(
            "Rental eligibility confirmed. Reimbursement processed."
        )

        liability = mocks.add_patch(f"{_STAGES}.create_liability_determination_crew")
        liability.return_value.kickoff.return_value = mock_crew_response(
            "Liability determination: not at fault."
        )

        settlement = mocks.add_patch(f"{_STAGES}.create_settlement_crew")
        settlement.return_value.kickoff.return_value = mock_crew_response(
            "Settlement completed."
        )

        subrogation = mocks.add_patch(f"{_STAGES}.create_subrogation_crew")
        subrogation.return_value.kickoff.return_value = mock_crew_response(
            "Subrogation assessment complete. No recovery opportunity."
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
    mock_crew_response,
    workflow_patches,
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

    with workflow_patches as mocks:
        mocks.set_router("bodily_injury", "Passenger injured in collision.")

        bi_crew = mocks.add_patch(f"{_STAGES}.create_bodily_injury_crew")
        bi_crew.return_value.kickoff.return_value = mock_crew_response(
            "BI settlement proposed.", tasks_output=workflow_tasks_output,
        )

        liability = mocks.add_patch(f"{_STAGES}.create_liability_determination_crew")
        liability.return_value.kickoff.return_value = mock_crew_response(
            "Liability determination: not at fault."
        )

        settlement = mocks.add_patch(f"{_STAGES}.create_settlement_crew")
        settlement.return_value.kickoff.return_value = mock_crew_response(
            "Settlement completed."
        )

        subrogation = mocks.add_patch(f"{_STAGES}.create_subrogation_crew")
        subrogation.return_value.kickoff.return_value = mock_crew_response(
            "Subrogation assessment complete. No recovery opportunity."
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
