"""Tests for bodily injury tools."""

import json
from unittest.mock import patch

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

    def test_claimant_id_included_in_response(self):
        """claimant_id is included in the response."""
        result = query_medical_records_impl("CLM-001", claimant_id="claimant-42")
        data = json.loads(result)
        assert data["claimant_id"] == "claimant-42"
        result_default = query_medical_records_impl("CLM-001")
        data_default = json.loads(result_default)
        assert data_default["claimant_id"] == "claimant-1"


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

    def test_medical_records_total_charges_affects_severity(self):
        """total_charges from medical records JSON affects severity (e.g. >50k -> severe)."""
        mr_high = json.dumps({"total_charges": 75000.0, "records": []})
        result_high = assess_injury_severity_impl("Minor bruise", medical_records_json=mr_high)
        data_high = json.loads(result_high)
        assert data_high["severity"] == "severe"

        mr_moderate = json.dumps({"total_charges": 15000.0, "records": []})
        result_mod = assess_injury_severity_impl("Minor bruise", medical_records_json=mr_moderate)
        data_mod = json.loads(result_mod)
        assert data_mod["severity"] == "moderate"


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

    def test_policy_bi_limits_used_when_available(self):
        """When policy returns BI limits, they are used instead of defaults."""
        mock_policy = {
            "bodily_injury": {"per_person": 100_000.0, "per_accident": 300_000.0},
        }
        mock_adapter = type("MockAdapter", (), {"get_policy": lambda self, pn: mock_policy})()

        with patch(
            "claim_agent.tools.bodily_injury_logic.get_policy_adapter",
            return_value=mock_adapter,
        ):
            result = calculate_bi_settlement_impl(
                claim_id="CLM-001",
                policy_number="POL-004",
                medical_charges=10_000.0,
                injury_severity="moderate",
            )
        data = json.loads(result)
        assert data["policy_bi_limit_per_person"] == 100_000.0
        assert data["policy_bi_limit_per_accident"] == 300_000.0
