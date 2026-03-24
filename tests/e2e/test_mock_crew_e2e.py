"""E2E tests for Mock Crew: submit + process and follow-up flow.

Tests use mocked LLM and mock crew environment so that no real LLM or external
API calls are made (CI-safe).  Follow-up notification test is marked xfail because
the crew kickoff is mocked and therefore does not exercise the notify_user path
needed to enqueue mock notifier responses.

Mirrors the patterns in tests/e2e/test_claim_submission_e2e.py.
"""

from unittest.mock import patch

import pytest

from claim_agent.config import reload_settings
from claim_agent.config.settings import get_adapter_backend, get_mock_crew_config
from claim_agent.db.constants import STATUS_OPEN
from claim_agent.mock_crew.notifier import (
    clear_all_pending_mock_responses,
    get_pending_mock_responses,
)


_STAGES = "claim_agent.workflow.stages"


# ============================================================================
# E2E: Submit + process with mock crew (always-on)
# ============================================================================


@pytest.mark.e2e
def test_e2e_mock_crew_submit_and_process(
    e2e_client,
    integration_db,
    sample_new_claim,
    mock_crew_response,
    mock_crew,
    workflow_patches,
):
    """Submit and process a new claim with mock crew enabled.

    Verifies that the full claim submission workflow succeeds with mock crew
    environment (MOCK_CREW_ENABLED=true, VISION_ADAPTER=mock) and that no real
    LLM or external API calls are made.
    """
    cfg = get_mock_crew_config()
    assert cfg["enabled"] is True, "mock_crew fixture should activate mock crew config"
    assert get_adapter_backend("vision") == "mock"

    with workflow_patches as mocks:
        mocks.set_router("new")
        crew = mocks.add_patch(f"{_STAGES}.create_new_claim_crew")
        crew.return_value.kickoff.return_value = mock_crew_response(
            "Claim processed with mock crew."
        )

        resp = e2e_client.post("/api/claims", json=sample_new_claim)

    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["claim_id"].startswith("CLM-")
    assert data["status"] == STATUS_OPEN
    assert data["claim_type"] == "new"

    history_resp = e2e_client.get(f"/api/claims/{data['claim_id']}/history")
    assert history_resp.status_code == 200
    actions = [h["action"] for h in history_resp.json()["history"]]
    assert "created" in actions
    assert "status_change" in actions


# ============================================================================
# E2E: Follow-up flow (xfail – requires Phase 4/5 integration)
# ============================================================================


@pytest.mark.e2e
@pytest.mark.xfail(
    reason=(
        "Full follow-up notification -> mock-intercept -> record-response loop requires "
        "the follow-up crew to call notify_user internally, which is not exercised when "
        "crew kickoff is mocked.  This test will pass once Phase 4/5 (mock notifier + "
        "claimant) is wired so that the follow-up orchestrator can trigger a real "
        "notify_user call that the mock notifier can intercept.  "
        "Tracked in docs/mock-crew-implementation-plan.md Phase 4/5."
    ),
    strict=False,
)
def test_e2e_mock_crew_follow_up_flow(
    e2e_client,
    integration_db,
    sample_new_claim,
    mock_crew_response,
    mock_llm_instance,
    mock_crew,
    monkeypatch,
    workflow_patches,
):
    """Follow-up flow: notify_user intercepted by mock notifier -> response queued.

    Steps:
    1. Submit a claim (mocked crew).
    2. Run the follow-up endpoint (mocked crew).
    3. Assert at least one pending mock response was queued by the mock notifier,
       meaning notify_user was called inside the crew (currently not the case with
       mocked kickoff, so the assertion fails -> xfail).
    4. Record a response via the record-response endpoint.

    This test will begin passing once the follow-up crew internally calls
    notify_user with MOCK_NOTIFIER_ENABLED=true.
    """
    monkeypatch.setenv("MOCK_NOTIFIER_ENABLED", "true")
    monkeypatch.setenv("MOCK_NOTIFIER_AUTO_RESPOND", "true")
    monkeypatch.setenv("MOCK_CLAIMANT_ENABLED", "true")
    reload_settings()

    clear_all_pending_mock_responses()

    # Step 1: submit claim
    with workflow_patches as mocks:
        mocks.set_router("new")
        crew = mocks.add_patch(f"{_STAGES}.create_new_claim_crew")
        crew.return_value.kickoff.return_value = mock_crew_response("OK")

        resp = e2e_client.post("/api/claims", json=sample_new_claim)

    assert resp.status_code == 200
    claim_id = resp.json()["claim_id"]

    # Step 2: run follow-up (crew mocked -> notify_user NOT called by crew)
    with (
        patch("claim_agent.workflow.follow_up_orchestrator.get_llm") as mock_llm2,
        patch("claim_agent.workflow.follow_up_orchestrator.create_follow_up_crew") as mock_follow,
    ):
        mock_llm2.return_value = mock_llm_instance
        mock_follow.return_value.kickoff.return_value = mock_crew_response(
            "Follow-up outreach sent to claimant."
        )
        follow_resp = e2e_client.post(
            f"/api/claims/{claim_id}/follow-up/run",
            json={"task": "Request damage photos from claimant."},
        )

    assert follow_resp.status_code == 200

    # Step 3: assert pending responses queued (xfail: empty because crew is mocked)
    pending = get_pending_mock_responses(claim_id)
    assert len(pending) > 0, (
        "Expected >=1 pending mock response from mock notifier intercept of notify_user; "
        "got 0 because mocked crew kickoff does not call notify_user."
    )

    # Step 4: record first response (would execute if step 3 passes)
    first_response = pending[0]
    messages_resp = e2e_client.get(f"/api/claims/{claim_id}/follow-up")
    assert messages_resp.status_code == 200
    messages = messages_resp.json()["messages"]
    assert len(messages) > 0
    message_id = messages[0]["id"]

    record_resp = e2e_client.post(
        f"/api/claims/{claim_id}/follow-up/record-response",
        json={"message_id": message_id, "response_content": first_response["response_text"]},
    )
    assert record_resp.status_code == 200
    assert record_resp.json()["success"] is True
