"""Unit tests for subrogation tools."""

import json


from claim_agent.tools.subrogation_logic import (
    assess_liability_impl,
    build_subrogation_case_impl,
    record_arbitration_filing_impl,
    record_recovery_impl,
    send_demand_letter_impl,
)


class TestAssessLiability:
    def test_not_at_fault_rear_ended(self):
        result = assess_liability_impl(
            incident_description="I was rear-ended by another driver at a stop light.",
        )
        data = json.loads(result)
        assert data["is_not_at_fault"] is True
        assert data["fault_determination"] == "not_at_fault"

    def test_at_fault_i_hit(self):
        result = assess_liability_impl(
            incident_description="I hit another vehicle. It was my fault.",
        )
        data = json.loads(result)
        assert data["is_not_at_fault"] is False
        assert data["fault_determination"] == "at_fault"

    def test_third_party_identified(self):
        result = assess_liability_impl(
            incident_description="The other driver hit me from behind.",
        )
        data = json.loads(result)
        assert data["third_party_identified"] is True


class TestBuildSubrogationCase:
    def test_build_case(self):
        liability = json.dumps({
            "is_not_at_fault": True,
            "third_party_identified": True,
            "third_party_notes": "Other driver mentioned.",
        })
        result = build_subrogation_case_impl(
            claim_id="CLM-123",
            payout_amount=15000.0,
            liability_assessment=liability,
        )
        data = json.loads(result)
        assert data["case_id"] == "SUB-CLM-123-001"
        assert data["amount_sought"] == 15000.0
        assert data["third_party_info"]["identified"] is True
        assert "status" in data

    def test_zero_liability_percentage_preserved(self):
        """Test that 0% liability (not at fault) is correctly preserved."""
        liability = json.dumps({
            "is_not_at_fault": True,
            "liability_percentage": 0,
            "liability_basis": "Insured 0% at fault - rear-ended",
        })
        claim_data = json.dumps({
            "liability_percentage": 50,
        })
        result = build_subrogation_case_impl(
            claim_id="CLM-456",
            payout_amount=10000.0,
            liability_assessment=liability,
            claim_data_json=claim_data,
        )
        data = json.loads(result)
        assert data["liability_percentage"] == 0.0
        assert data["liability_basis"] == "Insured 0% at fault - rear-ended"


class TestSendDemandLetter:
    def test_send_demand(self):
        result = send_demand_letter_impl(
            case_id="SUB-CLM-123-001",
            claim_id="CLM-123",
            amount_sought=15000.0,
        )
        data = json.loads(result)
        assert "confirmation" in data
        assert "letter_id" in data
        assert data["letter_id"].startswith("DEM-")
        assert data["amount_sought"] == 15000.0


class TestRecordArbitrationFiling:
    def test_record_arbitration(self):
        result = record_arbitration_filing_impl(
            case_id="SUB-CLM-123-001",
            arbitration_forum="Arbitration Forums Inc.",
        )
        data = json.loads(result)
        assert "confirmation" in data
        assert data["case_id"] == "SUB-CLM-123-001"
        assert data["arbitration_status"] == "filed"


class TestRecordRecovery:
    def test_record_pending(self):
        result = record_recovery_impl(
            claim_id="CLM-123",
            case_id="SUB-CLM-123-001",
            recovery_status="pending",
        )
        data = json.loads(result)
        assert data["recovery_status"] == "pending"
        assert data["claim_id"] == "CLM-123"

    def test_record_full_recovery(self):
        result = record_recovery_impl(
            claim_id="CLM-123",
            case_id="SUB-CLM-123-001",
            recovery_amount=15000.0,
            recovery_status="full",
        )
        data = json.loads(result)
        assert data["recovery_amount"] == 15000.0
        assert data["recovery_status"] == "full"
