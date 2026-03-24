"""E2E tests for Mock Crew: submit + process, follow-up flow, and mock vision.

Tests use mocked LLM and mock crew environment so that no real LLM or external
API calls are made (CI-safe).  Follow-up notification test is marked xfail because
the crew kickoff is mocked and therefore does not exercise the notify_user path
needed to enqueue mock notifier responses.

Mirrors the patterns in tests/e2e/test_claim_submission_e2e.py.
"""

import json
from unittest.mock import patch

import pytest

import claim_agent.storage.factory as factory_mod
from claim_agent.db.constants import STATUS_OPEN
from claim_agent.mock_crew.vision_mock import analyze_damage_photo_mock
from claim_agent.tools.vision_logic import analyze_damage_photo_impl


# ============================================================================
# Helpers
# ============================================================================


def _set_mock_crew_env(monkeypatch, *, notifier: bool = False) -> None:
    """Set environment variables for mock crew mode and reload settings."""
    from claim_agent.config import reload_settings

    monkeypatch.setenv("MOCK_CREW_ENABLED", "true")
    monkeypatch.setenv("VISION_ADAPTER", "mock")
    monkeypatch.setenv("MOCK_IMAGE_VISION_ANALYSIS_SOURCE", "claim_context")
    monkeypatch.setenv("MOCK_CREW_SEED", "42")
    if notifier:
        monkeypatch.setenv("MOCK_NOTIFIER_ENABLED", "true")
        monkeypatch.setenv("MOCK_NOTIFIER_AUTO_RESPOND", "true")
        monkeypatch.setenv("MOCK_CLAIMANT_ENABLED", "true")
    reload_settings()


# ============================================================================
# E2E: Submit + process with mock crew (always-on)
# ============================================================================


@pytest.mark.e2e
def test_e2e_mock_crew_submit_and_process(
    e2e_client,
    integration_db,
    sample_new_claim,
    mock_router_response,
    mock_crew_response,
    mock_llm_instance,
    monkeypatch,
):
    """Submit and process a new claim with mock crew enabled.

    Verifies that the full claim submission workflow succeeds with mock crew
    environment (MOCK_CREW_ENABLED=true, VISION_ADAPTER=mock) and that no real
    LLM or external API calls are made.
    """
    _set_mock_crew_env(monkeypatch)
    factory_mod._storage_instance = None

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.create_new_claim_crew") as mock_crew:
                with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                    with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                        with patch(
                            "claim_agent.workflow.stages.create_task_planner_crew"
                        ) as mock_task:
                            mock_llm.return_value = mock_llm_instance
                            mock_router.return_value.kickoff.return_value = mock_router_response(
                                "new"
                            )
                            mock_crew.return_value.kickoff.return_value = mock_crew_response(
                                "Claim processed with mock crew."
                            )
                            mock_after.return_value.kickoff.return_value = mock_crew_response(
                                "After-action complete."
                            )
                            mock_esc.return_value = json.dumps(
                                {
                                    "needs_review": False,
                                    "escalation_reasons": [],
                                    "priority": "low",
                                    "fraud_indicators": [],
                                    "recommended_action": "",
                                }
                            )
                            mock_task.return_value.kickoff.return_value = mock_crew_response(
                                "Tasks created."
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
        "Full follow-up notification → mock-intercept → record-response loop requires "
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
    mock_router_response,
    mock_crew_response,
    mock_llm_instance,
    monkeypatch,
):
    """Follow-up flow: notify_user intercepted by mock notifier → response queued.

    Steps:
    1. Submit a claim (mocked crew).
    2. Run the follow-up endpoint (mocked crew).
    3. Assert at least one pending mock response was queued by the mock notifier,
       meaning notify_user was called inside the crew (currently not the case with
       mocked kickoff, so the assertion fails → xfail).
    4. Record a response via the record-response endpoint.

    This test will begin passing once the follow-up crew internally calls
    notify_user with MOCK_NOTIFIER_ENABLED=true.
    """
    from claim_agent.mock_crew.notifier import (
        clear_all_pending_mock_responses,
        get_pending_mock_responses,
    )

    _set_mock_crew_env(monkeypatch, notifier=True)
    clear_all_pending_mock_responses()
    factory_mod._storage_instance = None

    # Step 1: submit claim
    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.create_new_claim_crew") as mock_crew:
                with patch("claim_agent.workflow.stages.create_after_action_crew") as mock_after:
                    with patch("claim_agent.workflow.stages.evaluate_escalation_impl") as mock_esc:
                        with patch(
                            "claim_agent.workflow.stages.create_task_planner_crew"
                        ) as mock_task:
                            mock_llm.return_value = mock_llm_instance
                            mock_router.return_value.kickoff.return_value = mock_router_response(
                                "new"
                            )
                            mock_crew.return_value.kickoff.return_value = mock_crew_response("OK")
                            mock_after.return_value.kickoff.return_value = mock_crew_response("OK")
                            mock_esc.return_value = json.dumps(
                                {
                                    "needs_review": False,
                                    "escalation_reasons": [],
                                    "priority": "low",
                                    "fraud_indicators": [],
                                    "recommended_action": "",
                                }
                            )
                            mock_task.return_value.kickoff.return_value = mock_crew_response("OK")
                            resp = e2e_client.post("/api/claims", json=sample_new_claim)

    assert resp.status_code == 200
    claim_id = resp.json()["claim_id"]

    # Step 2: run follow-up (crew mocked → notify_user NOT called by crew)
    with patch("claim_agent.workflow.follow_up_orchestrator.get_llm") as mock_llm2:
        with patch(
            "claim_agent.workflow.follow_up_orchestrator.create_follow_up_crew"
        ) as mock_follow:
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
        "Expected ≥1 pending mock response from mock notifier intercept of notify_user; "
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


# ============================================================================
# E2E: Mock vision analysis (always-on)
# ============================================================================


@pytest.mark.e2e
def test_e2e_mock_crew_vision(monkeypatch):
    """Mock vision analysis returns JSON consistent with seeded claim context.

    Exercises analyze_damage_photo_impl with VISION_ADAPTER=mock so that no
    real vision/LLM API call is made.  Assertions mirror tests/test_mock_crew_vision.py.
    """
    _set_mock_crew_env(monkeypatch)

    damage_description = "severe damage to bumper and fender after rear collision"
    claim_context = {
        "claim_id": "CLM-TEST-MOCK",
        "damage_description": damage_description,
    }

    # analyze_damage_photo_impl routes to analyze_damage_photo_mock when VISION_ADAPTER=mock
    raw = analyze_damage_photo_impl(
        "file://mock-image.jpg",
        damage_description,
        claim_context,
    )
    result = json.loads(raw)

    # Severity: "severe" keyword → "high"
    assert result["severity"] == "high"

    # Parts extracted from description
    assert "bumper" in result["parts_affected"]
    assert "fender" in result["parts_affected"]

    # Consistency: description present + parts inferred → consistent
    assert result["consistency_with_description"] == "consistent"

    # No error
    assert result.get("error") is None

    # Cross-check: same call via the low-level mock function yields identical output
    raw_direct = analyze_damage_photo_mock(
        "file://mock-image.jpg", damage_description, claim_context
    )
    assert json.loads(raw_direct) == result
