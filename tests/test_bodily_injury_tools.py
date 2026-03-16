"""Tests for bodily injury tools."""

import json
from unittest.mock import patch

from claim_agent.tools.bodily_injury_logic import (
    assess_injury_severity_impl,
    audit_medical_bills_impl,
    build_treatment_timeline_impl,
    calculate_bi_settlement_impl,
    calculate_loss_of_earnings_impl,
    check_cms_reporting_required_impl,
    check_minor_settlement_approval_impl,
    check_pip_medpay_exhaustion_impl,
    get_structured_settlement_option_impl,
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


class TestCheckPIPMedPayExhaustion:
    """Tests for check_pip_medpay_exhaustion_impl."""

    def test_no_fault_state_has_pip(self):
        """FL state has PIP; exhaustion depends on medical charges vs limit."""
        result = check_pip_medpay_exhaustion_impl(
            claim_id="CLM-001",
            policy_number="POL-001",
            medical_charges=15_000.0,
            loss_state="FL",
        )
        data = json.loads(result)
        assert data["has_pip_medpay"] is True
        assert data["pip_medpay_limit"] == 10_000.0
        assert data["exhausted"] is True
        assert data["bi_settlement_allowed"] is True

    def test_empty_claim_id_returns_error(self):
        """Empty claim_id returns error."""
        result = check_pip_medpay_exhaustion_impl(
            claim_id="",
            policy_number="POL-001",
            medical_charges=5000.0,
        )
        data = json.loads(result)
        assert "error" in data
        assert data["bi_settlement_allowed"] is False

    def test_full_state_name_new_york(self):
        """Full state name 'New York' correctly maps to NY abbreviation."""
        result = check_pip_medpay_exhaustion_impl(
            claim_id="CLM-002",
            policy_number="POL-002",
            medical_charges=60_000.0,
            loss_state="New York",
        )
        data = json.loads(result)
        assert data["has_pip_medpay"] is True
        assert data["pip_medpay_limit"] == 50_000.0
        assert data["exhausted"] is True
        assert data["bi_settlement_allowed"] is True

    def test_full_state_name_florida(self):
        """Full state name 'Florida' correctly maps to FL abbreviation."""
        result = check_pip_medpay_exhaustion_impl(
            claim_id="CLM-003",
            policy_number="POL-003",
            medical_charges=15_000.0,
            loss_state="Florida",
        )
        data = json.loads(result)
        assert data["has_pip_medpay"] is True
        assert data["pip_medpay_limit"] == 10_000.0
        assert data["exhausted"] is True
        assert data["bi_settlement_allowed"] is True


class TestCheckCMSReportingRequired:
    """Tests for check_cms_reporting_required_impl."""

    def test_medicare_eligible_over_threshold_requires_reporting(self):
        """Medicare beneficiary with settlement >= $750 requires reporting."""
        result = check_cms_reporting_required_impl(
            claim_id="CLM-001",
            settlement_amount=5000.0,
            claimant_medicare_eligible=True,
        )
        data = json.loads(result)
        assert data["reporting_required"] is True
        assert data["reporting_threshold"] == 750

    def test_below_threshold_no_reporting(self):
        """Settlement below $750 does not require reporting."""
        result = check_cms_reporting_required_impl(
            claim_id="CLM-001",
            settlement_amount=500.0,
            claimant_medicare_eligible=True,
        )
        data = json.loads(result)
        assert data["reporting_required"] is False


class TestCheckMinorSettlementApproval:
    """Tests for check_minor_settlement_approval_impl."""

    def test_minor_requires_court_approval(self):
        """Claimant under 18 requires court approval."""
        result = check_minor_settlement_approval_impl(
            claim_id="CLM-001",
            claimant_age=12,
            loss_state="CA",
        )
        data = json.loads(result)
        assert data["claimant_is_minor"] is True
        assert data["court_approval_required"] is True


class TestGetStructuredSettlementOption:
    """Tests for get_structured_settlement_option_impl."""

    def test_large_settlement_recommends_structure(self):
        """Settlement >= $100K recommends structured option."""
        result = get_structured_settlement_option_impl(
            claim_id="CLM-001",
            total_settlement=150_000.0,
        )
        data = json.loads(result)
        assert data["recommended"] is True
        assert data["lump_sum_amount"] > 0
        assert "periodic_payments" in data


class TestCalculateLossOfEarnings:
    """Tests for calculate_loss_of_earnings_impl."""

    def test_valid_inputs_returns_amount(self):
        """Valid wage and days missed returns recommended amount."""
        result = calculate_loss_of_earnings_impl(
            pre_accident_income=52_000.0,  # annual
            days_missed=10,
            income_type="w2",
        )
        data = json.loads(result)
        assert data["recommended_amount"] > 0
        assert "daily_rate" in data
        assert data["documentation_required"] is True


class TestAuditMedicalBills:
    """Tests for audit_medical_bills_impl."""

    def test_audit_returns_findings(self):
        """Audit returns total_allowed and reduction."""
        mr = json.dumps({
            "records": [
                {"provider": "ER", "charges": 3500, "date_of_service": "2024-01-15"},
                {"provider": "PCP", "charges": 250, "date_of_service": "2024-01-20"},
            ],
            "total_charges": 3750,
        })
        result = audit_medical_bills_impl(mr)
        data = json.loads(result)
        assert "total_billed" in data
        assert "total_allowed" in data
        assert "reduction_amount" in data
        assert data["total_allowed"] <= data["total_billed"]


class TestBuildTreatmentTimeline:
    """Tests for build_treatment_timeline_impl."""

    def test_timeline_from_records(self):
        """Build timeline from medical records."""
        mr = json.dumps({
            "records": [
                {"provider": "ER", "charges": 3500, "date_of_service": "2024-01-15", "treatment": "Exam", "diagnosis": "Strain"},
                {"provider": "PCP", "charges": 250, "date_of_service": "2024-01-25", "treatment": "Follow-up", "diagnosis": "Follow-up"},
            ],
            "total_charges": 3750,
        })
        result = build_treatment_timeline_impl(mr, incident_date="2024-01-10")
        data = json.loads(result)
        assert data["treatment_duration_days"] == 10
        assert len(data["events"]) == 2
        assert data["total_charges"] == 3750
