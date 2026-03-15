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
