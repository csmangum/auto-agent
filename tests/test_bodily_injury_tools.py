"""Tests for bodily injury tools."""

import json

from claim_agent.tools.bodily_injury_logic import (
    assess_injury_severity_impl,
    calculate_bi_settlement_impl,
    query_medical_records_impl,
)


class TestQueryMedicalRecords:
    """Tests for query_medical_records_impl."""

    def test_valid_claim_id_returns_records(self):
        """Valid claim_id returns medical records structure."""
        result = query_medical_records_impl("CLM-001")
        data = json.loads(result)
        assert "records" in data
        assert "total_charges" in data
        assert "treatment_summary" in data
        assert data["claim_id"] == "CLM-001"
        assert isinstance(data["records"], list)
        assert data["total_charges"] is not None

    def test_invalid_claim_id_returns_error(self):
        """Empty claim_id returns error structure."""
        result = query_medical_records_impl("")
        data = json.loads(result)
        assert "error" in data
        assert data["records"] == []
        assert data["total_charges"] is None


class TestAssessInjurySeverity:
    """Tests for assess_injury_severity_impl."""

    def test_minor_injury_keywords(self):
        """Minor injury keywords return minor severity."""
        result = assess_injury_severity_impl("Minor bruise and soreness")
        data = json.loads(result)
        assert data["severity"] == "minor"
        assert "recommended_range_low" in data
        assert "recommended_range_high" in data

    def test_moderate_injury_default(self):
        """Moderate injury description returns moderate severity."""
        result = assess_injury_severity_impl("Whiplash and cervical strain")
        data = json.loads(result)
        assert data["severity"] in ("minor", "moderate", "severe")
        assert data["recommended_range_low"] is not None
        assert data["recommended_range_high"] is not None

    def test_severe_injury_keywords(self):
        """Severe injury keywords return severe severity."""
        result = assess_injury_severity_impl("Fracture and surgery required")
        data = json.loads(result)
        assert data["severity"] == "severe"

    def test_invalid_description_returns_error(self):
        """Empty injury description returns error."""
        result = assess_injury_severity_impl("")
        data = json.loads(result)
        assert "error" in data
        assert data["severity"] is None


class TestCalculateBISettlement:
    """Tests for calculate_bi_settlement_impl."""

    def test_valid_inputs_returns_settlement(self):
        """Valid inputs return proposed settlement."""
        result = calculate_bi_settlement_impl(
            claim_id="CLM-001",
            policy_number="POL-001",
            medical_charges=5000.0,
            injury_severity="moderate",
        )
        data = json.loads(result)
        assert "proposed_settlement" in data
        assert data["proposed_settlement"] is not None
        assert data["medical_charges"] == 5000.0
        assert data["pain_suffering"] is not None
        assert "policy_bi_limit_per_person" in data

    def test_invalid_claim_id_returns_error(self):
        """Empty claim_id returns error."""
        result = calculate_bi_settlement_impl(
            claim_id="",
            policy_number="POL-001",
            medical_charges=5000.0,
            injury_severity="moderate",
        )
        data = json.loads(result)
        assert "error" in data
        assert data["proposed_settlement"] is None

    def test_invalid_medical_charges_returns_error(self):
        """Negative medical charges returns error."""
        result = calculate_bi_settlement_impl(
            claim_id="CLM-001",
            policy_number="POL-001",
            medical_charges=-100.0,
            injury_severity="moderate",
        )
        data = json.loads(result)
        assert "error" in data
        assert data["proposed_settlement"] is None
