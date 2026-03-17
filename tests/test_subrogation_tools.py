"""Unit tests for subrogation tools."""

import json

from sqlalchemy import text

from claim_agent.db.database import get_connection
from claim_agent.db.repository import ClaimRepository
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
        assert data["liability_percentage"] == 0.0

    def test_at_fault_i_hit(self):
        result = assess_liability_impl(
            incident_description="I hit another vehicle. It was my fault.",
        )
        data = json.loads(result)
        assert data["is_not_at_fault"] is False
        assert data["fault_determination"] == "at_fault"
        assert data["liability_percentage"] == 100.0

    def test_unclear_returns_none_liability_percentage(self):
        result = assess_liability_impl(
            incident_description="Something happened at the intersection.",
        )
        data = json.loads(result)
        assert data["fault_determination"] == "unclear"
        assert data["liability_percentage"] is None

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
    def test_record_arbitration(self, temp_db):
        # Use temp_db so impl uses same DB; create claim then subrogation case (FK).
        with get_connection(temp_db) as conn:
            conn.execute(
                text("""
                INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
                vehicle_model, incident_date, incident_description, damage_description,
                estimated_damage, claim_type, status)
                VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                        :incident_date, :incident_description, :damage_description,
                        :estimated_damage, :claim_type, :status)
                """),
                {
                    "id": "CLM-123",
                    "policy_number": "POL-123",
                    "vin": "1HGBH41JXMN109186",
                    "vehicle_year": 2021,
                    "vehicle_make": "Honda",
                    "vehicle_model": "Accord",
                    "incident_date": "2025-01-15",
                    "incident_description": "Rear-ended",
                    "damage_description": "Bumper damage",
                    "estimated_damage": 2500.0,
                    "claim_type": "new",
                    "status": "open",
                },
            )
        repo = ClaimRepository(temp_db)
        repo.create_subrogation_case(
            claim_id="CLM-123",
            case_id="SUB-CLM-123-001",
            amount_sought=15000.0,
        )
        result = record_arbitration_filing_impl(
            case_id="SUB-CLM-123-001",
            arbitration_forum="Arbitration Forums Inc.",
        )
        data = json.loads(result)
        assert "confirmation" in data
        assert data["case_id"] == "SUB-CLM-123-001"
        assert data["arbitration_status"] == "filed"

    def test_record_arbitration_nonexistent_case_returns_error(self):
        result = record_arbitration_filing_impl(
            case_id="SUB-NONEXISTENT-999",
            arbitration_forum="Arbitration Forums Inc.",
        )
        data = json.loads(result)
        assert "error" in data
        assert data["case_id"] == "SUB-NONEXISTENT-999"
        assert "not found" in data["error"].lower() or "subrogation" in data["error"].lower()


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

    def test_record_recovery_persists_when_case_exists(self, temp_db):
        """When subrogation case exists, record_recovery persists status and amount."""
        with get_connection(temp_db) as conn:
            conn.execute(
                text("""
                INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
                vehicle_model, incident_date, incident_description, damage_description,
                estimated_damage, claim_type, status)
                VALUES (:id, :policy_number, :vin, :vehicle_year, :vehicle_make, :vehicle_model,
                        :incident_date, :incident_description, :damage_description,
                        :estimated_damage, :claim_type, :status)
                """),
                {
                    "id": "CLM-REC",
                    "policy_number": "POL-1",
                    "vin": "1HGBH41JXMN109186",
                    "vehicle_year": 2021,
                    "vehicle_make": "Honda",
                    "vehicle_model": "Accord",
                    "incident_date": "2025-01-15",
                    "incident_description": "Rear-ended",
                    "damage_description": "Bumper",
                    "estimated_damage": 2500.0,
                    "claim_type": "new",
                    "status": "open",
                },
            )
        repo = ClaimRepository(temp_db)
        repo.create_subrogation_case(
            claim_id="CLM-REC",
            case_id="SUB-CLM-REC-001",
            amount_sought=5000.0,
        )
        result = record_recovery_impl(
            claim_id="CLM-REC",
            case_id="SUB-CLM-REC-001",
            recovery_amount=4500.0,
            recovery_status="partial",
        )
        data = json.loads(result)
        assert data["persisted"] is True
        cases = repo.get_subrogation_cases_by_claim("CLM-REC")
        assert len(cases) == 1
        assert cases[0]["status"] == "partial"
        assert cases[0]["recovery_amount"] == 4500.0

    def test_record_recovery_not_persisted_when_case_missing(self, temp_db):
        """When subrogation case does not exist, record_recovery returns persisted=False."""
        result = record_recovery_impl(
            claim_id="CLM-NONE",
            case_id="SUB-NONEXISTENT-001",
            recovery_amount=1000.0,
            recovery_status="full",
        )
        data = json.loads(result)
        assert data["persisted"] is False
