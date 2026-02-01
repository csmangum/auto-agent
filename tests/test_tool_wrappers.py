"""Unit tests for CrewAI tool wrappers (compliance, escalation, fraud).

These tests call the underlying tool functions directly via .run() method
or test the underlying _impl functions which are already tested in test_tools.py.
Here we focus on the tool wrappers to ensure they correctly parse input and delegate.
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

# Point to project data for mock_db
os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))

from claim_agent.db.database import init_db


@pytest.fixture(autouse=True)
def temp_db():
    """Use a temporary SQLite DB for tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    prev = os.environ.get("CLAIMS_DB_PATH")
    os.environ["CLAIMS_DB_PATH"] = path
    try:
        yield path
    finally:
        if prev is None:
            os.environ.pop("CLAIMS_DB_PATH", None)
        else:
            os.environ["CLAIMS_DB_PATH"] = prev
        try:
            os.unlink(path)
        except OSError:
            # Ignore errors when cleaning up the temporary DB file (e.g., if already removed).
            pass


class TestComplianceTools:
    """Tests for compliance_tools.py."""

    def test_search_california_compliance_tool_empty_query(self):
        """Test the compliance tool wrapper with empty query."""
        from claim_agent.tools.compliance_tools import search_california_compliance

        # Call via .run() method for CrewAI tools
        result = search_california_compliance.run(query="")
        data = json.loads(result)
        # Should return summary or error if file missing
        assert "sections" in data or "error" in data

    def test_search_california_compliance_tool_with_query(self):
        """Test the compliance tool wrapper with a query."""
        from claim_agent.tools.compliance_tools import search_california_compliance

        result = search_california_compliance.run(query="deadline")
        data = json.loads(result)
        assert "matches" in data or "error" in data


class TestEscalationTools:
    """Tests for escalation_tools.py tool wrappers."""

    def test_evaluate_escalation_tool_valid_json(self):
        """Test evaluate_escalation tool with valid JSON claim data."""
        from claim_agent.tools.escalation_tools import evaluate_escalation

        claim_data = json.dumps({
            "policy_number": "POL-001",
            "vin": "TEST123",
            "vehicle_year": 2022,
            "vehicle_make": "Tesla",
            "vehicle_model": "Model 3",
            "incident_date": "2025-01-20",
            "incident_description": "Minor parking lot ding.",
            "damage_description": "Small dent on door.",
            "estimated_damage": 500.0,
        })
        result = evaluate_escalation.run(claim_data=claim_data, router_output="new\nFirst-time submission.")
        data = json.loads(result)
        assert "needs_review" in data
        assert "escalation_reasons" in data
        assert "priority" in data

    def test_evaluate_escalation_tool_invalid_json(self):
        """Test evaluate_escalation tool with invalid JSON (handles gracefully)."""
        from claim_agent.tools.escalation_tools import evaluate_escalation

        result = evaluate_escalation.run(claim_data="not valid json", router_output="new")
        data = json.loads(result)
        # Should still return valid response structure
        assert "needs_review" in data

    def test_evaluate_escalation_tool_empty_claim(self):
        """Test evaluate_escalation tool with empty claim data."""
        from claim_agent.tools.escalation_tools import evaluate_escalation

        result = evaluate_escalation.run(claim_data="", router_output="new\nStandard claim.")
        data = json.loads(result)
        assert "needs_review" in data

    def test_evaluate_escalation_tool_with_similarity(self):
        """Test evaluate_escalation tool with similarity score."""
        from claim_agent.tools.escalation_tools import evaluate_escalation

        claim_data = json.dumps({
            "policy_number": "POL-001",
            "vin": "TEST123",
            "incident_date": "2025-01-20",
            "incident_description": "Bumper damage.",
            "damage_description": "Bumper damage.",
        })
        result = evaluate_escalation.run(claim_data=claim_data, router_output="duplicate\nSimilar to existing.", similarity_score="65", payout_amount="")
        data = json.loads(result)
        assert data["needs_review"] is True
        assert "ambiguous_similarity" in data["escalation_reasons"]

    def test_evaluate_escalation_tool_with_high_payout(self):
        """Test evaluate_escalation tool with high payout triggers escalation."""
        from claim_agent.tools.escalation_tools import evaluate_escalation

        claim_data = json.dumps({
            "policy_number": "POL-001",
            "vin": "TEST123",
            "incident_date": "2025-01-20",
            "incident_description": "Front collision.",
            "damage_description": "Front damage.",
        })
        result = evaluate_escalation.run(claim_data=claim_data, router_output="new\nClear.", similarity_score="", payout_amount="15000")
        data = json.loads(result)
        assert data["needs_review"] is True
        assert "high_value" in data["escalation_reasons"]

    def test_evaluate_escalation_tool_invalid_similarity(self):
        """Test evaluate_escalation tool with invalid similarity score."""
        from claim_agent.tools.escalation_tools import evaluate_escalation

        claim_data = json.dumps({"vin": "TEST"})
        result = evaluate_escalation.run(claim_data=claim_data, router_output="new", similarity_score="not_a_number", payout_amount="")
        data = json.loads(result)
        # Should handle gracefully
        assert "needs_review" in data

    def test_evaluate_escalation_tool_invalid_payout(self):
        """Test evaluate_escalation tool with invalid payout amount."""
        from claim_agent.tools.escalation_tools import evaluate_escalation

        claim_data = json.dumps({"vin": "TEST"})
        result = evaluate_escalation.run(claim_data=claim_data, router_output="new", similarity_score="", payout_amount="invalid")
        data = json.loads(result)
        assert "needs_review" in data

    def test_detect_fraud_indicators_tool_valid_json(self):
        """Test detect_fraud_indicators tool with valid JSON."""
        from claim_agent.tools.escalation_tools import detect_fraud_indicators

        claim_data = json.dumps({
            "incident_description": "Staged accident with multiple occupants.",
            "damage_description": "Suspicious damage.",
            "vin": "TEST123",
            "incident_date": "2025-01-20",
        })
        result = detect_fraud_indicators.run(claim_data=claim_data)
        indicators = json.loads(result)
        assert isinstance(indicators, list)
        assert len(indicators) >= 1

    def test_detect_fraud_indicators_tool_invalid_json(self):
        """Test detect_fraud_indicators tool with invalid JSON."""
        from claim_agent.tools.escalation_tools import detect_fraud_indicators

        result = detect_fraud_indicators.run(claim_data="not json")
        indicators = json.loads(result)
        assert isinstance(indicators, list)

    def test_detect_fraud_indicators_tool_empty(self):
        """Test detect_fraud_indicators tool with empty string."""
        from claim_agent.tools.escalation_tools import detect_fraud_indicators

        result = detect_fraud_indicators.run(claim_data="")
        indicators = json.loads(result)
        assert indicators == []

    def test_generate_escalation_report_valid(self):
        """Test generate_escalation_report with valid inputs."""
        from claim_agent.tools.escalation_tools import generate_escalation_report

        result = generate_escalation_report.run(
            claim_id="CLM-TEST001",
            needs_review="true",
            escalation_reasons='["high_value", "low_confidence"]',
            priority="high",
            recommended_action="Review claim manually.",
            fraud_indicators='["staged"]',
        )
        assert "CLM-TEST001" in result
        assert "true" in result.lower() or "True" in result
        assert "high" in result.lower()
        assert "high_value" in result
        assert "staged" in result

    def test_generate_escalation_report_no_review(self):
        """Test generate_escalation_report when no review needed."""
        from claim_agent.tools.escalation_tools import generate_escalation_report

        result = generate_escalation_report.run(
            claim_id="CLM-TEST002",
            needs_review="false",
            escalation_reasons="[]",
            priority="low",
            recommended_action="No action needed.",
            fraud_indicators="[]",
        )
        assert "CLM-TEST002" in result
        assert "false" in result.lower() or "False" in result
        assert "low" in result.lower()

    def test_generate_escalation_report_invalid_json_reasons(self):
        """Test generate_escalation_report with invalid JSON reasons."""
        from claim_agent.tools.escalation_tools import generate_escalation_report

        result = generate_escalation_report.run(
            claim_id="CLM-TEST003",
            needs_review="true",
            escalation_reasons="not valid json",
            priority="medium",
            recommended_action="Review.",
            fraud_indicators="also not json",
        )
        assert "CLM-TEST003" in result
        # Should handle gracefully
        assert "None" in result


class TestFraudTools:
    """Tests for fraud_tools.py tool wrappers."""

    def test_analyze_claim_patterns_tool_valid_json(self):
        """Test analyze_claim_patterns tool with valid JSON."""
        from claim_agent.tools.fraud_tools import analyze_claim_patterns

        claim_data = json.dumps({
            "vin": "TEST123",
            "incident_date": "2025-01-20",
            "incident_description": "Multiple occupants all injured.",
            "damage_description": "Front damage.",
        })
        result = analyze_claim_patterns.run(claim_data=claim_data)
        data = json.loads(result)
        assert "patterns_detected" in data
        assert "pattern_score" in data

    def test_analyze_claim_patterns_tool_invalid_json(self):
        """Test analyze_claim_patterns tool with invalid JSON."""
        from claim_agent.tools.fraud_tools import analyze_claim_patterns

        result = analyze_claim_patterns.run(claim_data="not valid json")
        data = json.loads(result)
        assert "patterns_detected" in data
        assert data["patterns_detected"] == []

    def test_analyze_claim_patterns_tool_with_vin(self):
        """Test analyze_claim_patterns tool with explicit VIN parameter."""
        from claim_agent.tools.fraud_tools import analyze_claim_patterns

        result = analyze_claim_patterns.run(claim_data="{}", vin="EXPLICIT_VIN_123")
        data = json.loads(result)
        assert data["vin"] == "EXPLICIT_VIN_123"

    def test_cross_reference_fraud_indicators_tool_valid(self):
        """Test cross_reference_fraud_indicators tool with valid data."""
        from claim_agent.tools.fraud_tools import cross_reference_fraud_indicators

        claim_data = json.dumps({
            "incident_description": "Staged accident with inflated claims.",
            "damage_description": "Pre-existing damage and exaggerated repairs.",
        })
        result = cross_reference_fraud_indicators.run(claim_data=claim_data)
        data = json.loads(result)
        assert "fraud_keywords_found" in data
        assert "risk_level" in data
        assert "cross_reference_score" in data

    def test_cross_reference_fraud_indicators_tool_invalid_json(self):
        """Test cross_reference_fraud_indicators tool with invalid JSON."""
        from claim_agent.tools.fraud_tools import cross_reference_fraud_indicators

        result = cross_reference_fraud_indicators.run(claim_data="not json")
        data = json.loads(result)
        assert data["fraud_keywords_found"] == []
        assert data["risk_level"] == "low"

    def test_perform_fraud_assessment_tool_valid(self):
        """Test perform_fraud_assessment tool with valid data."""
        from claim_agent.tools.fraud_tools import perform_fraud_assessment

        claim_data = json.dumps({
            "vin": "TEST123",
            "incident_date": "2025-01-20",
            "incident_description": "Minor fender bender.",
            "damage_description": "Small dent.",
            "estimated_damage": 500,
        })
        result = perform_fraud_assessment.run(claim_data=claim_data)
        data = json.loads(result)
        assert "fraud_score" in data
        assert "fraud_likelihood" in data
        assert "should_block" in data
        assert "siu_referral" in data

    def test_perform_fraud_assessment_tool_invalid_json(self):
        """Test perform_fraud_assessment tool with invalid JSON."""
        from claim_agent.tools.fraud_tools import perform_fraud_assessment

        result = perform_fraud_assessment.run(claim_data="not json")
        data = json.loads(result)
        assert "Invalid claim data" in data["recommended_action"]

    def test_perform_fraud_assessment_tool_with_pattern_analysis(self):
        """Test perform_fraud_assessment tool with pattern analysis."""
        from claim_agent.tools.fraud_tools import perform_fraud_assessment

        claim_data = json.dumps({
            "vin": "TEST123",
            "incident_description": "Minor accident.",
            "damage_description": "Bumper damage.",
        })
        pattern_analysis = json.dumps({
            "patterns_detected": ["staged_accident_indicators"],
            "pattern_score": 20,
        })
        result = perform_fraud_assessment.run(claim_data=claim_data, pattern_analysis=pattern_analysis)
        data = json.loads(result)
        assert data["fraud_score"] >= 20

    def test_perform_fraud_assessment_tool_with_cross_reference(self):
        """Test perform_fraud_assessment tool with cross-reference data."""
        from claim_agent.tools.fraud_tools import perform_fraud_assessment

        claim_data = json.dumps({
            "vin": "TEST123",
            "incident_description": "Minor accident.",
            "damage_description": "Bumper damage.",
        })
        cross_ref = json.dumps({
            "fraud_keywords_found": ["staged"],
            "database_matches": [],
            "cross_reference_score": 20,
        })
        result = perform_fraud_assessment.run(claim_data=claim_data, pattern_analysis="", cross_reference=cross_ref)
        data = json.loads(result)
        assert data["fraud_score"] >= 20

    def test_perform_fraud_assessment_tool_invalid_pattern_json(self):
        """Test perform_fraud_assessment with invalid pattern JSON."""
        from claim_agent.tools.fraud_tools import perform_fraud_assessment

        result = perform_fraud_assessment.run(claim_data='{"vin": "TEST"}', pattern_analysis="not json", cross_reference="")
        data = json.loads(result)
        # Should handle gracefully
        assert "fraud_score" in data

    def test_generate_fraud_report_tool_valid(self):
        """Test generate_fraud_report tool with valid inputs."""
        from claim_agent.tools.fraud_tools import generate_fraud_report

        result = generate_fraud_report.run(
            claim_id="CLM-TEST001",
            fraud_likelihood="high",
            fraud_score="75",
            fraud_indicators='["staged", "inflated"]',
            recommended_action="Refer to SIU.",
            siu_referral="true",
            should_block="false",
        )
        assert "CLM-TEST001" in result
        assert "HIGH" in result
        assert "75" in result
        assert "staged" in result
        assert "SIU Referral Required: YES" in result
        assert "Claim Blocked: No" in result

    def test_generate_fraud_report_tool_blocked(self):
        """Test generate_fraud_report tool with blocked claim."""
        from claim_agent.tools.fraud_tools import generate_fraud_report

        result = generate_fraud_report.run(
            claim_id="CLM-TEST002",
            fraud_likelihood="critical",
            fraud_score="100",
            fraud_indicators='["multiple_fraud_indicators"]',
            recommended_action="Block claim immediately.",
            siu_referral="true",
            should_block="true",
        )
        assert "CRITICAL" in result
        assert "Claim Blocked: YES - DO NOT PROCESS" in result

    def test_generate_fraud_report_tool_no_indicators(self):
        """Test generate_fraud_report tool with no indicators."""
        from claim_agent.tools.fraud_tools import generate_fraud_report

        result = generate_fraud_report.run(
            claim_id="CLM-TEST003",
            fraud_likelihood="low",
            fraud_score="0",
            fraud_indicators="[]",
            recommended_action="Process normally.",
        )
        assert "LOW" in result
        assert "None detected" in result

    def test_generate_fraud_report_tool_invalid_json_indicators(self):
        """Test generate_fraud_report with invalid JSON indicators."""
        from claim_agent.tools.fraud_tools import generate_fraud_report

        result = generate_fraud_report.run(
            claim_id="CLM-TEST004",
            fraud_likelihood="medium",
            fraud_score="not_a_number",
            fraud_indicators="not json",
            recommended_action="Review.",
        )
        assert "CLM-TEST004" in result
        assert "0" in result  # Invalid score should default to 0
        assert "None detected" in result  # Invalid indicators should be empty
