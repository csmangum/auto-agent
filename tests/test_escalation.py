"""Tests for HITL escalation: low confidence, high value, fraud indicators."""

import json
import os
from pathlib import Path

import pytest

# Point to project data for mock_db
os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))

# Skip full workflow integration test if no LLM (OPENAI_API_KEY)
SKIP_WORKFLOW = not os.environ.get("OPENAI_API_KEY")


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
    from claim_agent.tools.logic import evaluate_escalation_impl

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
    from claim_agent.tools.logic import evaluate_escalation_impl

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
    from claim_agent.tools.logic import evaluate_escalation_impl

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
    from claim_agent.tools.logic import evaluate_escalation_impl

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


def test_escalation_priority_multiple_reasons():
    """Multiple escalation reasons yield higher priority."""
    from claim_agent.tools.logic import compute_escalation_priority_impl

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
    from claim_agent.tools.logic import evaluate_escalation_impl

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
    from claim_agent.tools.logic import detect_fraud_indicators_impl

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


def test_parse_router_confidence():
    """Router confidence decreases with uncertainty language."""
    from claim_agent.tools.logic import _parse_router_confidence

    high = _parse_router_confidence("new\nFirst-time submission.")
    assert high >= 0.9

    low = _parse_router_confidence("possibly duplicate. Unclear. Might be new.")
    assert low < 0.8


def test_escalation_output_structure():
    """evaluate_escalation_impl returns expected keys."""
    from claim_agent.tools.logic import evaluate_escalation_impl

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


@pytest.mark.skipif(SKIP_WORKFLOW, reason="OPENAI_API_KEY not set; skip run_claim_workflow integration test")
def test_run_claim_workflow_escalation_high_value(_temp_claims_db):
    """Integration: run_claim_workflow with high-value claim escalates and returns NEEDS_REVIEW."""
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
    result = run_claim_workflow(claim_data)
    assert result["status"] == STATUS_NEEDS_REVIEW
    assert "high_value" in result["escalation_reasons"]
