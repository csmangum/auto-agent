"""Tests for HITL escalation: low confidence, high value, fraud indicators."""

import json
import os
from pathlib import Path

import pytest

# Point to project data for mock_db
os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))


@pytest.fixture(autouse=True)
def _temp_claims_db(tmp_path, monkeypatch):
    """
    Ensure tests use a temporary SQLite DB for claims instead of data/claims.db.
    This keeps tests hermetic and avoids writing to the repository filesystem.
    """
    from claim_agent.db.database import init_db

    db_path = tmp_path / "claims.db"
    monkeypatch.setenv("CLAIMS_DB_PATH", str(db_path))
    init_db(str(db_path))


def test_escalation_high_value_triggers():
    """High-value claim (estimated_damage >= threshold) triggers escalation."""
    from claim_agent.tools.escalation_logic import evaluate_escalation_impl

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Front bumper scratch.",
        "damage_description": "Scratches on bumper.",
        "estimated_damage": 15000.0,
    }
    router_output = "new\nFirst-time submission."
    result = evaluate_escalation_impl(claim_data, router_output, None, None)
    data = json.loads(result)
    assert data["needs_review"] is True
    assert "high_value" in data["escalation_reasons"]
    assert data["priority"] in ("low", "medium", "high", "critical")


def test_escalation_low_confidence_triggers():
    """Low-confidence routing (uncertainty language in router output) triggers escalation."""
    from claim_agent.tools.escalation_logic import evaluate_escalation_impl

    # Use descriptions with enough word overlap to avoid fraud "incident_damage_description_mismatch"
    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Minor damage to bumper.",
        "damage_description": "Damage to bumper.",
        "estimated_damage": 500.0,
    }
    # Three uncertainty words so confidence < 0.7 (0.15 * 3 = 0.45 -> 0.55)
    router_output = "possibly duplicate. Unclear. Might be new or duplicate."
    result = evaluate_escalation_impl(claim_data, router_output, None, None)
    data = json.loads(result)
    assert data["needs_review"] is True
    assert "low_confidence" in data["escalation_reasons"]


def test_escalation_fraud_indicators_triggers():
    """Fraud-related keywords in description trigger fraud_suspected escalation."""
    from claim_agent.tools.escalation_logic import evaluate_escalation_impl

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Staged accident with multiple occupants.",
        "damage_description": "Suspicious damage patterns.",
        "estimated_damage": 2000.0,
    }
    router_output = "new\nFirst-time claim."
    result = evaluate_escalation_impl(claim_data, router_output, None, None)
    data = json.loads(result)
    assert data["needs_review"] is True
    assert "fraud_suspected" in data["escalation_reasons"]
    assert len(data["fraud_indicators"]) >= 1


def test_escalation_ambiguous_similarity_triggers():
    """Similarity score in ambiguous range (50-80%) triggers escalation."""
    from claim_agent.tools.escalation_logic import evaluate_escalation_impl

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Rear-ended at stoplight.",
        "damage_description": "Bumper damage.",
        "estimated_damage": 1500.0,
    }
    router_output = "duplicate\nSimilar to existing claim."
    result = evaluate_escalation_impl(claim_data, router_output, similarity_score=65.0, payout_amount=None)
    data = json.loads(result)
    assert data["needs_review"] is True
    assert "ambiguous_similarity" in data["escalation_reasons"]


def test_validate_router_classification_uses_minimized_data():
    """Router validation prompt should use minimized claim data, not full claim payload."""
    from unittest.mock import MagicMock, patch

    from claim_agent.tools.escalation_logic import validate_router_classification_impl

    claim_data = {
        "claim_id": "CLM-123",
        "policy_number": "POL-12345-001",
        "vin": "1HGCM82633A123456",
        "incident_description": "Rear-end collision at stoplight",
        "damage_description": "Rear bumper damage",
        "claimant_name": "Jane Doe",  # not allowed for router payload
        "secret_field": "must_not_be_sent",
    }

    mocked_response = MagicMock()
    mocked_response.choices = [MagicMock(message=MagicMock(content='{"claim_type":"new","confidence":0.8,"reasoning":"ok"}'))]
    mocked_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    mocked_response.model = "test-model"

    with patch("claim_agent.tools.escalation_logic.litellm") as mock_litellm:
        mock_litellm.completion.return_value = mocked_response

        result = validate_router_classification_impl(
            claim_data,
            "new",
            0.6,
            "initial router output",
        )

    assert '"claim_type": "new"' in result
    mock_litellm.completion.assert_called_once()
    called_prompt = mock_litellm.completion.call_args.kwargs.get("messages", [{}])[0].get("content", "")
    assert "secret_field" not in called_prompt
    assert "claimant_name" not in called_prompt


def test_escalation_priority_multiple_reasons():
    """Multiple escalation reasons yield higher priority."""
    from claim_agent.tools.escalation_logic import compute_escalation_priority_impl

    # 1 reason -> low
    r = json.loads(compute_escalation_priority_impl(["high_value"], []))
    assert r["priority"] == "low"

    # 2 reasons -> medium
    r = json.loads(compute_escalation_priority_impl(["high_value", "low_confidence"], []))
    assert r["priority"] == "medium"

    # 3+ reasons -> high
    r = json.loads(compute_escalation_priority_impl(["high_value", "low_confidence", "ambiguous_similarity"], []))
    assert r["priority"] == "high"

    # fraud_suspected -> high
    r = json.loads(compute_escalation_priority_impl(["fraud_suspected"], ["staged"]))
    assert r["priority"] == "high"

    # multiple fraud indicators -> critical
    r = json.loads(compute_escalation_priority_impl(["fraud_suspected", "high_value"], ["staged", "inflated"]))
    assert r["priority"] == "critical"


def test_escalation_normal_claim_no_escalation():
    """Normal claim (low value, clear routing, no fraud) does not escalate."""
    from claim_agent.tools.escalation_logic import evaluate_escalation_impl

    # Unique VIN so no multiple_claims_same_vin; shared words so no incident_damage_description_mismatch
    claim_data = {
        "policy_number": "POL-001",
        "vin": "UNIQUEVIN999NOCLAIMS",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Bumper damage and scratch.",
        "damage_description": "Damage and scratch on bumper.",
        "estimated_damage": 1200.0,
    }
    router_output = "new\nFirst-time submission, standard intake."
    result = evaluate_escalation_impl(claim_data, router_output, None, None)
    data = json.loads(result)
    assert data["needs_review"] is False
    assert data["escalation_reasons"] == []
    assert data["priority"] == "low"
    assert "No escalation needed" in data["recommended_action"]


def test_detect_fraud_indicators_keywords():
    """detect_fraud_indicators returns indicators for fraud-related keywords."""
    from claim_agent.tools.escalation_logic import detect_fraud_indicators_impl

    claim_data = {
        "incident_description": "Staged accident with multiple occupants.",
        "damage_description": "Suspicious damage.",
        "vin": "X",
        "incident_date": "2025-01-01",
    }
    result = detect_fraud_indicators_impl(claim_data)
    indicators = json.loads(result)
    assert isinstance(indicators, list)
    assert len(indicators) >= 1


def test_detect_fraud_indicators_accepts_date_object():
    """detect_fraud_indicators handles date-typed incident_date."""
    from datetime import date
    from claim_agent.tools.escalation_logic import detect_fraud_indicators_impl

    claim_data = {
        "incident_description": "Minor bump in parking lot.",
        "damage_description": "Scratch on bumper.",
        "vin": "VIN123",
        "incident_date": date(2025, 1, 1),
    }
    result = detect_fraud_indicators_impl(claim_data)
    indicators = json.loads(result)
    assert isinstance(indicators, list)


def test_detect_fraud_indicators_accepts_datetime_object():
    """detect_fraud_indicators handles datetime-typed incident_date."""
    from datetime import datetime
    from claim_agent.tools.escalation_logic import detect_fraud_indicators_impl

    claim_data = {
        "incident_description": "Minor bump in parking lot.",
        "damage_description": "Scratch on bumper.",
        "vin": "VIN123",
        "incident_date": datetime(2025, 1, 1, 12, 0, 0),
    }
    result = detect_fraud_indicators_impl(claim_data)
    indicators = json.loads(result)
    assert isinstance(indicators, list)


def test_get_escalation_evidence_returns_evidence_only():
    """get_escalation_evidence_impl returns rule outputs as evidence, no decisions."""
    from claim_agent.tools.escalation_logic import get_escalation_evidence_impl

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Front bumper scratch.",
        "damage_description": "Scratches on bumper.",
        "estimated_damage": 500.0,
    }
    result = get_escalation_evidence_impl(claim_data, "new\nFirst-time submission.")
    data = json.loads(result)
    assert "fraud_indicators" in data
    assert "router_confidence" in data
    assert "high_value" in data
    assert "needs_review" not in data
    assert "escalation_reasons" not in data


def test_get_description_overlap_evidence():
    """get_description_overlap_evidence returns score and threshold."""
    from claim_agent.tools.fraud_detectors import get_description_overlap_evidence

    claim_data = {
        "incident_description": "Rear-ended at stoplight. Bumper hit.",
        "damage_description": "Rear bumper dented and scratched.",
    }
    result = get_description_overlap_evidence(claim_data)
    assert result is not None
    assert "score" in result
    assert "threshold" in result
    assert 0 <= result["score"] <= 1
    assert result["threshold"] > 0


def test_parse_router_confidence():
    """Router confidence decreases with uncertainty language."""
    from claim_agent.tools.escalation_logic import _parse_router_confidence

    high = _parse_router_confidence("new\nFirst-time submission.")
    assert high >= 0.9

    low = _parse_router_confidence("possibly duplicate. Unclear. Might be new.")
    assert low < 0.8


def test_escalation_output_structure():
    """evaluate_escalation_impl returns expected keys."""
    from claim_agent.tools.escalation_logic import evaluate_escalation_impl

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Minor damage.",
        "damage_description": "Bumper scratch.",
        "estimated_damage": 500.0,
    }
    result = evaluate_escalation_impl(claim_data, "new\nClear.", None, None)
    data = json.loads(result)
    assert "needs_review" in data
    assert "escalation_reasons" in data
    assert "priority" in data
    assert "fraud_indicators" in data
    assert "recommended_action" in data


def test_extract_json_handles_braces_in_reasoning():
    """_extract_json_from_text handles JSON with braces in string values (e.g. reasoning)."""
    from claim_agent.tools.escalation_logic import _extract_json_from_text

    text = 'Here is the result: {"claim_type": "partial_loss", "confidence": 0.9, "reasoning": "Damage is {severe}."}'
    parsed = _extract_json_from_text(text)
    assert parsed is not None
    assert parsed["claim_type"] == "partial_loss"
    assert parsed["confidence"] == 0.9
    assert parsed["reasoning"] == "Damage is {severe}."


def test_evaluate_escalation_uses_explicit_router_confidence():
    """When router_confidence is passed, it overrides keyword inference."""
    from claim_agent.tools.escalation_logic import evaluate_escalation_impl

    claim_data = {
        "policy_number": "POL-001",
        "vin": "UNIQUEVIN999NOCLAIMS",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Bumper damage.",
        "damage_description": "Bumper scratch.",
        "estimated_damage": 500.0,
    }
    # Router output with uncertainty keywords would normally give low confidence
    router_output = "possibly new. Unclear."
    # But explicit confidence 0.9 should override -> no low_confidence reason
    result = evaluate_escalation_impl(
        claim_data, router_output, None, None, router_confidence=0.9
    )
    data = json.loads(result)
    assert "low_confidence" not in data["escalation_reasons"]
    assert data["needs_review"] is False

    # Explicit low confidence should trigger
    result2 = evaluate_escalation_impl(
        claim_data, "new\nClear.", None, None, router_confidence=0.5
    )
    data2 = json.loads(result2)
    assert "low_confidence" in data2["escalation_reasons"]


def test_escalation_output_model_validate_from_main_crew_dict():
    """EscalationOutput validates the dict shape returned by main_crew when escalated."""
    from claim_agent.models.claim import EscalationOutput

    d = {
        "claim_id": "CLM-ABC12345",
        "needs_review": True,
        "escalation_reasons": ["high_value"],
        "priority": "low",
        "recommended_action": "Review claim manually. Verify valuation and damage estimate. ",
        "fraud_indicators": [],
    }
    out = EscalationOutput.model_validate(d)
    assert out.claim_id == "CLM-ABC12345"
    assert out.needs_review is True
    assert out.priority == "low"
    assert out.priority in ("low", "medium", "high", "critical")


def test_run_claim_workflow_escalates_on_low_router_confidence(_temp_claims_db):
    """When router returns low confidence (< threshold), claim escalates before workflow."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Minor damage.",
        "damage_description": "Bumper scratch.",
        "estimated_damage": 500.0,
    }
    # Mock router to return JSON with low confidence (0.5 < 0.7 threshold)
    router_low_conf_raw = '{"claim_type": "new", "confidence": 0.5, "reasoning": "Unclear damage."}'
    no_escalation = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.evaluate_escalation_impl", return_value=no_escalation):
                mock_llm.return_value = MagicMock()
                mock_router.return_value.kickoff.return_value = MagicMock(raw=router_low_conf_raw)

                result = run_claim_workflow(claim_data)

    assert result["status"] == STATUS_NEEDS_REVIEW
    assert result["needs_review"] is True
    assert "low_router_confidence" in result.get("escalation_reasons", [])
    assert "0.5" in result.get("summary", "") or "threshold" in result.get("summary", "").lower()


def test_run_claim_workflow_validation_enabled_agrees_high_confidence(_temp_claims_db):
    """Validation enabled: validator agrees and returns high confidence → workflow proceeds."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Minor bumper damage.",
        "damage_description": "Bumper scratch.",
        "estimated_damage": 500.0,
    }
    router_low_conf_raw = '{"claim_type": "new", "confidence": 0.5, "reasoning": "Unclear."}'
    # Validator agrees: same claim_type, high confidence
    val_result = json.dumps({
        "claim_type": "new",
        "confidence": 0.9,
        "reasoning": "First-time submission confirmed.",
        "validation_agrees": True,
    })
    no_escalation = json.dumps({
        "needs_review": False,
        "escalation_reasons": [],
        "priority": "low",
        "fraud_indicators": [],
        "recommended_action": "",
    })
    workflow_output = MagicMock()
    workflow_output.raw = "Claim processed successfully."

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm, \
         patch("claim_agent.workflow.stages.create_router_crew") as mock_router, \
         patch("claim_agent.workflow.stages.get_router_config", return_value={"confidence_threshold": 0.7, "validation_enabled": True}), \
         patch("claim_agent.workflow.stages.validate_router_classification_impl", return_value=val_result), \
         patch("claim_agent.workflow.stages.evaluate_escalation_impl", return_value=no_escalation), \
         patch("claim_agent.workflow.stages.create_new_claim_crew") as mock_crew, \
         patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner, \
         patch("claim_agent.workflow.stages.create_after_action_crew") as mock_aa:
        mock_llm.return_value = MagicMock()
        mock_router.return_value.kickoff.return_value = MagicMock(raw=router_low_conf_raw)
        mock_crew.return_value.kickoff.return_value = workflow_output
        mock_task_planner.return_value.kickoff.return_value = MagicMock(raw="Tasks created.")
        mock_aa.return_value.kickoff.return_value = MagicMock(raw="After-action complete.")

        result = run_claim_workflow(claim_data)

    # Claim should NOT be escalated; it should proceed to the new-claim workflow
    assert result.get("status") != STATUS_NEEDS_REVIEW
    assert result.get("claim_type") == "new"


def test_run_claim_workflow_validation_enabled_disagrees_reclassifies(_temp_claims_db):
    """Validation enabled: validator disagrees and returns high confidence → reclassified and proceeds."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW

    claim_data = {
        "policy_number": "POL-003",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Rear-end collision with major damage.",
        "damage_description": "Frame bent; vehicle may be a total loss.",
        "estimated_damage": 500.0,
    }
    router_low_conf_raw = '{"claim_type": "new", "confidence": 0.5, "reasoning": "Unclear."}'
    # Validator disagrees: different claim_type, high confidence
    val_result = json.dumps({
        "claim_type": "total_loss",
        "confidence": 0.88,
        "reasoning": "Frame damage indicates total loss.",
        "validation_agrees": False,
    })
    no_escalation = json.dumps({
        "needs_review": False,
        "escalation_reasons": [],
        "priority": "low",
        "fraud_indicators": [],
        "recommended_action": "",
    })
    workflow_output = MagicMock()
    workflow_output.raw = "Total loss settlement initiated."
    settlement_output = MagicMock()
    settlement_output.raw = "Settlement completed."

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm, \
         patch("claim_agent.workflow.stages.create_router_crew") as mock_router, \
         patch("claim_agent.workflow.stages.get_router_config", return_value={"confidence_threshold": 0.7, "validation_enabled": True}), \
         patch("claim_agent.workflow.stages.validate_router_classification_impl", return_value=val_result), \
         patch("claim_agent.workflow.stages.evaluate_escalation_impl", return_value=no_escalation), \
         patch("claim_agent.workflow.stages.create_total_loss_crew") as mock_tl_crew, \
         patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner, \
         patch("claim_agent.workflow.stages.create_liability_determination_crew") as mock_liability, \
         patch("claim_agent.workflow.stages.create_settlement_crew") as mock_settle_crew, \
         patch("claim_agent.workflow.stages.create_subrogation_crew") as mock_subrogation, \
         patch("claim_agent.workflow.stages.create_salvage_crew") as mock_salvage, \
         patch("claim_agent.workflow.stages.create_after_action_crew") as mock_aa:
        mock_llm.return_value = MagicMock()
        mock_router.return_value.kickoff.return_value = MagicMock(raw=router_low_conf_raw)
        mock_tl_crew.return_value.kickoff.return_value = workflow_output
        mock_task_planner.return_value.kickoff.return_value = MagicMock(raw="Tasks created.")
        mock_liability.return_value.kickoff.return_value = MagicMock(raw="Liability determined.")
        mock_settle_crew.return_value.kickoff.return_value = settlement_output
        mock_subrogation.return_value.kickoff.return_value = MagicMock(raw="Subrogation assessment complete.")
        mock_salvage.return_value.kickoff.return_value = MagicMock(raw="Salvage disposition complete.")
        mock_aa.return_value.kickoff.return_value = MagicMock(raw="After-action complete.")

        result = run_claim_workflow(claim_data)

    # Reclassified to total_loss, not escalated
    assert result.get("status") != STATUS_NEEDS_REVIEW
    assert result.get("claim_type") == "total_loss"


def test_run_claim_workflow_validation_enabled_low_confidence_escalates(_temp_claims_db):
    """Validation enabled: validator also returns low confidence → claim escalates."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW

    claim_data = {
        "policy_number": "POL-004",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Minor damage.",
        "damage_description": "Bumper scratch.",
        "estimated_damage": 500.0,
    }
    router_low_conf_raw = '{"claim_type": "new", "confidence": 0.5, "reasoning": "Unclear."}'
    # Validator also returns low confidence
    val_result = json.dumps({
        "claim_type": "new",
        "confidence": 0.4,
        "reasoning": "Still uncertain after review.",
        "validation_agrees": True,
    })

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm, \
         patch("claim_agent.workflow.stages.create_router_crew") as mock_router, \
         patch("claim_agent.workflow.stages.get_router_config", return_value={"confidence_threshold": 0.7, "validation_enabled": True}), \
         patch("claim_agent.workflow.stages.validate_router_classification_impl", return_value=val_result):
        mock_llm.return_value = MagicMock()
        mock_router.return_value.kickoff.return_value = MagicMock(raw=router_low_conf_raw)

        result = run_claim_workflow(claim_data)

    assert result["status"] == STATUS_NEEDS_REVIEW
    assert result["needs_review"] is True
    assert "low_router_confidence" in result.get("escalation_reasons", [])


def test_run_claim_workflow_validation_parse_error_escalates(_temp_claims_db):
    """Validation enabled: validator returns invalid JSON → parse error fallback escalates."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW

    claim_data = {
        "policy_number": "POL-005",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Minor damage.",
        "damage_description": "Bumper scratch.",
        "estimated_damage": 500.0,
    }
    router_low_conf_raw = '{"claim_type": "new", "confidence": 0.5, "reasoning": "Unclear."}'

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm, \
         patch("claim_agent.workflow.stages.create_router_crew") as mock_router, \
         patch("claim_agent.workflow.stages.get_router_config", return_value={"confidence_threshold": 0.7, "validation_enabled": True}), \
         patch("claim_agent.workflow.stages.validate_router_classification_impl", return_value="not valid json {{"):
        mock_llm.return_value = MagicMock()
        mock_router.return_value.kickoff.return_value = MagicMock(raw=router_low_conf_raw)

        result = run_claim_workflow(claim_data)

    assert result["status"] == STATUS_NEEDS_REVIEW
    assert result["needs_review"] is True
    assert "low_router_confidence" in result.get("escalation_reasons", [])


def test_run_claim_workflow_validation_non_numeric_confidence_escalates(_temp_claims_db):
    """Validation enabled: validator returns non-numeric confidence (ValueError) → escalates."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW

    claim_data = {
        "policy_number": "POL-006",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Minor damage.",
        "damage_description": "Bumper scratch.",
        "estimated_damage": 500.0,
    }
    router_low_conf_raw = '{"claim_type": "new", "confidence": 0.5, "reasoning": "Unclear."}'
    # Confidence is a non-numeric string; float() raises ValueError
    val_result = json.dumps({"claim_type": "new", "confidence": "high", "reasoning": "Looks new."})

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm, \
         patch("claim_agent.workflow.stages.create_router_crew") as mock_router, \
         patch("claim_agent.workflow.stages.get_router_config", return_value={"confidence_threshold": 0.7, "validation_enabled": True}), \
         patch("claim_agent.workflow.stages.validate_router_classification_impl", return_value=val_result):
        mock_llm.return_value = MagicMock()
        mock_router.return_value.kickoff.return_value = MagicMock(raw=router_low_conf_raw)

        result = run_claim_workflow(claim_data)

    assert result["status"] == STATUS_NEEDS_REVIEW
    assert result["needs_review"] is True
    assert "low_router_confidence" in result.get("escalation_reasons", [])


def test_run_claim_workflow_escalation_high_value(_temp_claims_db):
    """run_claim_workflow with high-value claim escalates and returns NEEDS_REVIEW."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Front bumper scratch.",
        "damage_description": "Scratches on bumper.",
        "estimated_damage": 15000.0,
    }
    router_high_conf_raw = '{"claim_type": "new", "confidence": 0.9, "reasoning": "First-time submission."}'

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm, \
         patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
        mock_llm.return_value = MagicMock()
        mock_router.return_value.kickoff.return_value = MagicMock(raw=router_high_conf_raw)

        result = run_claim_workflow(claim_data)

    assert result["status"] == STATUS_NEEDS_REVIEW
    assert "high_value" in result["escalation_reasons"]


# --- Mid-Workflow Escalation Tests ---


def test_escalate_claim_impl_updates_db(_temp_claims_db):
    """escalate_claim_impl sets status to needs_review and persists escalation details."""
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput
    from claim_agent.tools.escalation_logic import escalate_claim_impl
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW
    from datetime import date

    repo = ClaimRepository()
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="5YJSA1E26HF123456",
        vehicle_year=2022,
        vehicle_make="Tesla",
        vehicle_model="Model 3",
        incident_date=date(2025, 1, 20),
        incident_description="Minor damage.",
        damage_description="Bumper scratch.",
    )
    claim_id = repo.create_claim(claim_input)

    escalate_claim_impl(
        claim_id=claim_id,
        reason="damage_inconsistent_with_incident",
        indicators=["incident_damage_mismatch"],
        priority="high",
    )

    claim = repo.get_claim(claim_id)
    assert claim["status"] == STATUS_NEEDS_REVIEW
    assert claim["priority"] == "high"
    assert claim.get("due_at") is not None

    history, _ = repo.get_claim_history(claim_id)
    escalation_entries = [h for h in history if h.get("action") == "escalation"]
    assert len(escalation_entries) >= 1


def test_escalate_claim_tool_raises_mid_workflow_escalation(_temp_claims_db):
    """escalate_claim tool raises MidWorkflowEscalation after persisting to DB."""
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput
    from claim_agent.tools.escalation_tools import escalate_claim
    from claim_agent.exceptions import MidWorkflowEscalation
    from datetime import date

    repo = ClaimRepository()
    claim_input = ClaimInput(
        policy_number="POL-001",
        vin="5YJSA1E26HF123456",
        vehicle_year=2022,
        vehicle_make="Tesla",
        vehicle_model="Model 3",
        incident_date=date(2025, 1, 20),
        incident_description="Minor damage.",
        damage_description="Bumper scratch.",
    )
    claim_id = repo.create_claim(claim_input)
    claim_data = json.dumps({"claim_id": claim_id, "vin": "5YJSA1E26HF123456"})

    with pytest.raises(MidWorkflowEscalation) as exc_info:
        escalate_claim.run(claim_data=claim_data, reason="fraud_indicators", indicators='["staged"]', priority="critical")

    e = exc_info.value
    assert e.claim_id == claim_id
    assert e.reason == "fraud_indicators"
    assert e.indicators == ["staged"]
    assert e.priority == "critical"

    claim = repo.get_claim(claim_id)
    assert claim["status"] == "needs_review"


def test_escalate_claim_impl_raises_for_missing_claim_id():
    """escalate_claim_impl raises ValueError when claim_id is empty."""
    from claim_agent.tools.escalation_logic import escalate_claim_impl

    with pytest.raises(ValueError, match="claim_id is required"):
        escalate_claim_impl(claim_id="", reason="test", indicators=[], priority="low")

    with pytest.raises(ValueError, match="claim_id is required"):
        escalate_claim_impl(claim_id="   ", reason="test", indicators=[], priority="low")


def test_escalate_claim_impl_raises_for_missing_reason():
    """escalate_claim_impl raises ValueError when reason is empty."""
    from claim_agent.tools.escalation_logic import escalate_claim_impl

    with pytest.raises(ValueError, match="reason is required"):
        escalate_claim_impl(claim_id="CLM-12345678", reason="", indicators=[], priority="low")


def test_escalate_claim_impl_raises_for_invalid_indicators():
    """escalate_claim_impl raises ValueError when indicators is not a list or tuple."""
    from claim_agent.tools.escalation_logic import escalate_claim_impl

    with pytest.raises(ValueError, match="indicators must be a list or tuple"):
        escalate_claim_impl(
            claim_id="CLM-12345678",
            reason="test",
            indicators="not a list",  # type: ignore[arg-type]
            priority="low",
        )


def test_main_crew_handles_mid_workflow_escalation(_temp_claims_db):
    """When crew raises MidWorkflowEscalation, main_crew returns escalation response and saves escalation details."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW
    from claim_agent.exceptions import MidWorkflowEscalation
    from claim_agent.tools.escalation_logic import escalate_claim_impl

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF123456",
        "vehicle_year": 2022,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model 3",
        "incident_date": "2025-01-20",
        "incident_description": "Minor damage.",
        "damage_description": "Bumper scratch.",
        "estimated_damage": 500.0,
    }

    def mock_kickoff(inputs=None, **kwargs):
        # Simulate escalate_claim tool: persist to DB then raise (tool always does this)
        if inputs and "claim_data" in inputs:
            data = json.loads(inputs["claim_data"]) if isinstance(inputs["claim_data"], str) else inputs["claim_data"]
            claim_id = data.get("claim_id")
            if claim_id:
                escalate_claim_impl(
                    claim_id=claim_id,
                    reason="damage_inconsistent_with_incident",
                    indicators=["incident_damage_mismatch"],
                    priority="high",
                )
        raise MidWorkflowEscalation(
            reason="damage_inconsistent_with_incident",
            indicators=["incident_damage_mismatch"],
            priority="high",
            claim_id="will-be-overridden",
        )

    no_escalation = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.create_total_loss_crew") as mock_crew:
                with patch("claim_agent.workflow.stages.evaluate_escalation_impl", return_value=no_escalation):
                    mock_llm.return_value = MagicMock()
                    mock_router.return_value.kickoff.return_value = MagicMock(
                        raw="total_loss\nVehicle damage suggests total loss."
                    )
                    mock_crew.return_value.kickoff.side_effect = mock_kickoff

                    result = run_claim_workflow(claim_data)

    assert result["status"] == STATUS_NEEDS_REVIEW
    assert result["needs_review"] is True
    assert "damage_inconsistent_with_incident" in result["escalation_reasons"]
    assert result["priority"] == "high"
    assert "Escalated mid-workflow" in result["summary"]

    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository()
    claim_id = result["claim_id"]
    claim = repo.get_claim(claim_id)
    assert claim["status"] == STATUS_NEEDS_REVIEW


def test_settlement_crew_handles_mid_workflow_escalation(_temp_claims_db):
    """When the settlement crew raises MidWorkflowEscalation, main_crew returns an escalation
    response with stage='settlement' and persists STATUS_NEEDS_REVIEW."""
    from unittest.mock import MagicMock, patch

    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.constants import STATUS_NEEDS_REVIEW
    from claim_agent.exceptions import MidWorkflowEscalation
    from claim_agent.tools.escalation_logic import escalate_claim_impl

    claim_data = {
        "policy_number": "POL-001",
        "vin": "5YJSA1E26HF654321",
        "vehicle_year": 2021,
        "vehicle_make": "Tesla",
        "vehicle_model": "Model S",
        "incident_date": "2025-02-10",
        "incident_description": "Vehicle rolled over.",
        "damage_description": "Total loss, vehicle destroyed.",
        "estimated_damage": 45000.0,
    }

    def primary_crew_kickoff(inputs=None, **kwargs):
        return MagicMock(raw="Primary workflow complete.")

    def settlement_crew_kickoff(inputs=None, **kwargs):
        if inputs and "claim_data" in inputs:
            data = json.loads(inputs["claim_data"]) if isinstance(inputs["claim_data"], str) else inputs["claim_data"]
            claim_id = data.get("claim_id")
            if claim_id:
                escalate_claim_impl(
                    claim_id=claim_id,
                    reason="settlement_compliance_issue",
                    indicators=["missing_documentation"],
                    priority="medium",
                )
        raise MidWorkflowEscalation(
            reason="settlement_compliance_issue",
            indicators=["missing_documentation"],
            priority="medium",
            claim_id="will-be-overridden",
        )

    no_escalation = '{"needs_review": false, "escalation_reasons": [], "priority": "low", "fraud_indicators": [], "recommended_action": ""}'

    with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
        with patch("claim_agent.workflow.stages.create_router_crew") as mock_router:
            with patch("claim_agent.workflow.stages.create_total_loss_crew") as mock_primary_crew:
                with patch("claim_agent.workflow.stages.create_task_planner_crew") as mock_task_planner:
                    with patch("claim_agent.workflow.stages.create_liability_determination_crew") as mock_liability:
                        with patch("claim_agent.workflow.stages.create_settlement_crew") as mock_settlement_crew:
                            with patch("claim_agent.workflow.stages.evaluate_escalation_impl", return_value=no_escalation):
                                mock_llm.return_value = MagicMock()
                                mock_router.return_value.kickoff.return_value = MagicMock(
                                    raw="total_loss\nVehicle is a total loss."
                                )
                                mock_primary_crew.return_value.kickoff.side_effect = primary_crew_kickoff
                                mock_task_planner.return_value.kickoff.return_value = MagicMock(raw="Tasks created.")
                                mock_liability.return_value.kickoff.return_value = MagicMock(raw="Liability determined.")
                                mock_settlement_crew.return_value.kickoff.side_effect = settlement_crew_kickoff

                                result = run_claim_workflow(claim_data)

    assert result["status"] == STATUS_NEEDS_REVIEW
    assert result["needs_review"] is True
    assert "settlement_compliance_issue" in result["escalation_reasons"]
    assert result["priority"] == "medium"
    assert "Escalated during settlement" in result["summary"]

    # workflow_output is a combined text string: primary output + settlement escalation details.
    # Confirm it contains the primary output and the settlement stage marker.
    workflow_output = result["workflow_output"]
    assert "Primary workflow complete." in workflow_output
    assert "settlement" in workflow_output
    assert "settlement_compliance_issue" in workflow_output

    from claim_agent.db.repository import ClaimRepository

    repo = ClaimRepository()
    claim_id = result["claim_id"]
    claim = repo.get_claim(claim_id)
    assert claim["status"] == STATUS_NEEDS_REVIEW
