"""Unit tests for SIU investigation tools."""

import json
import os
import tempfile

import pytest

from claim_agent.db.database import init_db
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput


@pytest.fixture
def temp_db():
    """Temp DB with CLAIMS_DB_PATH set."""
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
            pass


class TestGetSiuCaseDetailsImpl:
    def test_returns_case_when_found(self, temp_db):
        """get_siu_case_details_impl returns case data when case exists."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.tools.siu_logic import get_siu_case_details_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-123", indicators=["high_value"])
        result = get_siu_case_details_impl(case_id)
        data = json.loads(result)
        assert data["case_id"] == case_id
        assert data["claim_id"] == "CLM-123"
        assert data["status"] == "open"
        assert "notes" in data

    def test_returns_error_when_not_found(self):
        """get_siu_case_details_impl returns error JSON when case does not exist."""
        from claim_agent.tools.siu_logic import get_siu_case_details_impl

        result = get_siu_case_details_impl("SIU-MOCK-NONEXISTENT")
        data = json.loads(result)
        assert "error" in data
        assert "not found" in data["error"].lower() or "Case not found" in data["error"]


class TestAddSiuInvestigationNoteImpl:
    def test_adds_note_successfully(self):
        """add_siu_investigation_note_impl adds note and returns success."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.tools.siu_logic import add_siu_investigation_note_impl, get_siu_case_details_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-456", indicators=[])
        result = add_siu_investigation_note_impl(case_id, "Document verified", category="document_review")
        data = json.loads(result)
        assert data["success"] is True
        assert data["case_id"] == case_id
        assert data["category"] == "document_review"

        case_result = get_siu_case_details_impl(case_id)
        case_data = json.loads(case_result)
        assert len(case_data["notes"]) == 1
        assert case_data["notes"][0]["note"] == "Document verified"
        assert case_data["notes"][0]["category"] == "document_review"

    def test_rejects_invalid_category(self):
        """add_siu_investigation_note_impl returns error JSON for invalid category."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.tools.siu_logic import add_siu_investigation_note_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-CAT", indicators=[])
        result = add_siu_investigation_note_impl(case_id, "Note", category="invalid_category")
        data = json.loads(result)
        assert data["success"] is False
        assert "Invalid category" in data["message"]
        assert "invalid_category" in data["message"]


class TestUpdateSiuCaseStatusImpl:
    def test_updates_status_successfully(self):
        """update_siu_case_status_impl updates status and returns success."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.tools.siu_logic import get_siu_case_details_impl, update_siu_case_status_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-789", indicators=[])
        result = update_siu_case_status_impl(case_id, "closed")
        data = json.loads(result)
        assert data["success"] is True
        assert data["status"] == "closed"

        case_result = get_siu_case_details_impl(case_id)
        case_data = json.loads(case_result)
        assert case_data["status"] == "closed"

    def test_rejects_invalid_status(self):
        """update_siu_case_status_impl returns error JSON for invalid status."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.tools.siu_logic import update_siu_case_status_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-VALID", indicators=[])
        result = update_siu_case_status_impl(case_id, "invalid_status")
        data = json.loads(result)
        assert data["success"] is False
        assert "Invalid status" in data["message"]
        assert "invalid_status" in data["message"]


class TestVerifyDocumentAuthenticityImpl:
    def test_returns_structured_result(self):
        """verify_document_authenticity_impl returns verified, confidence, findings."""
        from claim_agent.tools.siu_logic import verify_document_authenticity_impl

        result = verify_document_authenticity_impl("proof_of_loss", "CLM-ABC123")
        data = json.loads(result)
        assert "document_type" in data
        assert "verified" in data
        assert "confidence" in data
        assert "findings" in data
        assert "recommendation" in data
        assert data["document_type"] in ("proof_of_loss", "other")


class TestCheckClaimantInvestigationHistoryImpl:
    def test_returns_low_risk_when_no_prior_claims(self, temp_db):
        """check_claimant_investigation_history_impl returns low risk when no prior fraud/SIU."""
        from claim_agent.context import ClaimContext
        from claim_agent.tools.siu_logic import check_claimant_investigation_history_impl

        repo = ClaimRepository(db_path=temp_db)
        inp = ClaimInput(
            policy_number="POL-NEW",
            vin="VIN-NEW-999",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-01-15",
            incident_description="First claim",
            damage_description="Minor",
        )
        claim_id = repo.create_claim(inp)

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        result = check_claimant_investigation_history_impl(claim_id, ctx=ctx)
        data = json.loads(result)
        assert data["claim_id"] == claim_id
        assert data["risk_summary"] == "low"
        assert data["prior_claims"] == []
        assert data["prior_fraud_flags"] == []
        assert data["prior_siu_cases"] == []

    def test_uses_vin_from_claim_when_not_provided(self, temp_db):
        """check_claimant_investigation_history_impl uses claim VIN when vin param empty."""
        from claim_agent.context import ClaimContext
        from claim_agent.tools.siu_logic import check_claimant_investigation_history_impl

        repo = ClaimRepository(db_path=temp_db)
        inp = ClaimInput(
            policy_number="POL-VIN",
            vin="VIN-FROM-CLAIM",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Minor",
        )
        claim_id = repo.create_claim(inp)

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        result = check_claimant_investigation_history_impl(claim_id, vin="", policy_number="", ctx=ctx)
        data = json.loads(result)
        assert data["claim_id"] == claim_id
        assert "prior_claims" in data

    def test_returns_elevated_risk_when_prior_fraud_on_same_vin(self, temp_db):
        """check_claimant_investigation_history_impl returns elevated risk when prior fraud on same VIN."""
        from claim_agent.context import ClaimContext
        from claim_agent.tools.siu_logic import check_claimant_investigation_history_impl

        repo = ClaimRepository(db_path=temp_db)
        shared_vin = "VIN-SHARED-FRAUD"
        inp_current = ClaimInput(
            policy_number="POL-CURRENT",
            vin=shared_vin,
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-02-01",
            incident_description="Current claim",
            damage_description="Minor",
        )
        claim_id_current = repo.create_claim(inp_current)

        inp_prior = ClaimInput(
            policy_number="POL-PRIOR",
            vin=shared_vin,
            vehicle_year=2020,
            vehicle_make="Toyota",
            vehicle_model="Camry",
            incident_date="2025-01-10",
            incident_description="Prior claim",
            damage_description="Bumper",
        )
        claim_id_prior = repo.create_claim(inp_prior)
        repo.update_claim_status(claim_id_prior, "fraud_suspected", actor_id="fraud_crew")

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        result = check_claimant_investigation_history_impl(claim_id_current, ctx=ctx)
        data = json.loads(result)
        assert data["claim_id"] == claim_id_current
        assert data["risk_summary"] == "elevated"
        assert claim_id_prior in data["prior_fraud_flags"]
        assert len(data["prior_claims"]) >= 1

    def test_returns_high_risk_when_prior_siu_on_same_vin(self, temp_db):
        """check_claimant_investigation_history_impl returns high risk when prior SIU case on same VIN."""
        from claim_agent.context import ClaimContext
        from claim_agent.tools.siu_logic import check_claimant_investigation_history_impl

        repo = ClaimRepository(db_path=temp_db)
        shared_vin = "VIN-SHARED-SIU"
        inp_current = ClaimInput(
            policy_number="POL-CURRENT-SIU",
            vin=shared_vin,
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-02-15",
            incident_description="Current claim",
            damage_description="Minor",
        )
        claim_id_current = repo.create_claim(inp_current)

        inp_prior = ClaimInput(
            policy_number="POL-PRIOR-SIU",
            vin=shared_vin,
            vehicle_year=2020,
            vehicle_make="Toyota",
            vehicle_model="Camry",
            incident_date="2025-01-05",
            incident_description="Prior claim with SIU",
            damage_description="Total",
        )
        claim_id_prior = repo.create_claim(inp_prior)
        repo.update_claim_siu_case_id(claim_id_prior, "SIU-MOCK-PRIOR", actor_id="fraud_crew")

        ctx = ClaimContext.from_defaults(db_path=temp_db)
        result = check_claimant_investigation_history_impl(claim_id_current, ctx=ctx)
        data = json.loads(result)
        assert data["claim_id"] == claim_id_current
        assert data["risk_summary"] == "high"
        assert "SIU-MOCK-PRIOR" in data["prior_siu_cases"]


class TestFileFraudReportStateBureauImpl:
    def test_returns_mock_confirmation(self):
        """file_fraud_report_state_bureau_impl returns success and report_id."""
        from claim_agent.tools.siu_logic import file_fraud_report_state_bureau_impl

        result = file_fraud_report_state_bureau_impl("CLM-001", "SIU-001", state="California", indicators='["staged"]')
        data = json.loads(result)
        assert data["success"] is True
        assert "report_id" in data
        assert "FRB-" in data["report_id"]
        assert data["claim_id"] == "CLM-001"
        assert data["case_id"] == "SIU-001"
        assert data["state"] == "California"
