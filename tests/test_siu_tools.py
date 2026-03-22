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

    def test_returns_error_json_when_adapter_raises(self, monkeypatch):
        """get_siu_case_details_impl returns error JSON (does not raise) when adapter fails."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.tools.siu_logic import get_siu_case_details_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-ERR", indicators=[])

        def failing_get_case(cid):
            raise ConnectionError("Adapter timeout")

        monkeypatch.setattr(adapter, "get_case", failing_get_case)

        result = get_siu_case_details_impl(case_id)
        data = json.loads(result)
        assert "error" in data
        assert data.get("tool_failure") is True
        assert "timeout" in data["error"].lower() or "ConnectionError" in data["error"]

    def test_retries_on_transient_failure_then_succeeds(self, monkeypatch):
        """get_siu_case_details_impl retries on ConnectionError and succeeds on third attempt."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.tools.siu_logic import get_siu_case_details_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-RETRY", indicators=[])
        original_get_case = adapter.get_case
        call_count = 0

        def patched_get_case(cid):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary failure")
            return original_get_case(cid)

        monkeypatch.setattr(adapter, "get_case", patched_get_case)

        result = get_siu_case_details_impl(case_id)
        data = json.loads(result)
        assert "error" not in data
        assert data["case_id"] == case_id
        assert call_count == 3


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

    def test_returns_error_json_when_repository_raises_connection_error(self, temp_db, monkeypatch):
        """check_claimant_investigation_history_impl returns tool_failure JSON when repo raises ConnectionError."""
        from claim_agent.context import ClaimContext
        from claim_agent.tools.siu_logic import check_claimant_investigation_history_impl

        ctx = ClaimContext.from_defaults(db_path=temp_db)

        def failing_get_claim(cid):
            raise ConnectionError("Database unreachable")

        monkeypatch.setattr(ctx.repo, "get_claim", failing_get_claim)

        result = check_claimant_investigation_history_impl("CLM-ANY", ctx=ctx)
        data = json.loads(result)
        assert "error" in data
        assert data.get("tool_failure") is True
        assert "Records lookup failed" in data["error"]


class TestSiuScopeValidation:
    """Tests for SIU workflow scope (IDOR prevention)."""

    def test_rejects_wrong_case_id_when_scope_set(self):
        """get_siu_case_details_impl returns access denied when case_id does not match scope."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.observability import siu_workflow_scope
        from claim_agent.tools.siu_logic import get_siu_case_details_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-123", indicators=[])
        with siu_workflow_scope(claim_id="CLM-123", case_id=case_id):
            result = get_siu_case_details_impl("SIU-WRONG-CASE")
        data = json.loads(result)
        assert data.get("error") == "Access denied"

    def test_allows_matching_case_id_when_scope_set(self):
        """get_siu_case_details_impl succeeds when case_id matches scope."""
        from claim_agent.adapters.registry import get_siu_adapter
        from claim_agent.observability import siu_workflow_scope
        from claim_agent.tools.siu_logic import get_siu_case_details_impl

        adapter = get_siu_adapter()
        case_id = adapter.create_case("CLM-123", indicators=[])
        with siu_workflow_scope(claim_id="CLM-123", case_id=case_id):
            result = get_siu_case_details_impl(case_id)
        data = json.loads(result)
        assert data["case_id"] == case_id
        assert "error" not in data


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
        assert data["report_id"].startswith("FRB-CA-")

    def test_persists_filing_for_audit(self, temp_db):
        """file_fraud_report_state_bureau_impl persists filing to fraud_report_filings."""
        from datetime import date

        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.observability import siu_workflow_scope
        from claim_agent.tools.siu_logic import file_fraud_report_state_bureau_impl

        repo = ClaimRepository()
        claim_id = repo.create_claim(
            ClaimInput(
                policy_number="POL-FRAUD",
                vin="VIN-FRAUD",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date=date(2026, 1, 15),
                incident_description="Staged accident",
                damage_description="Inflated damage",
                estimated_damage=5000,
            )
        )
        case_id = "SIU-MOCK-FILING"
        with siu_workflow_scope(claim_id=claim_id, case_id=case_id):
            result = file_fraud_report_state_bureau_impl(
                claim_id, case_id, state="California", indicators='["staged", "inflated"]'
            )
        data = json.loads(result)
        assert data["success"] is True
        filings = repo.get_fraud_filings_for_claim(claim_id)
        assert len(filings) == 1
        assert filings[0]["filing_type"] == "state_bureau"
        assert filings[0]["report_id"] == data["report_id"]
        assert filings[0]["state"] == "California"
        assert filings[0]["indicators_count"] == 2

    def test_retries_on_transient_failure_then_succeeds(self, monkeypatch):
        """file_fraud_report_state_bureau_impl retries transient adapter failures."""
        from claim_agent.adapters.registry import get_state_bureau_adapter
        from claim_agent.tools.siu_logic import file_fraud_report_state_bureau_impl

        adapter = get_state_bureau_adapter()
        original = adapter.submit_fraud_report
        call_count = 0

        def patched_submit_fraud_report(*, claim_id, case_id, state, indicators):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Temporary state bureau outage")
            return original(
                claim_id=claim_id,
                case_id=case_id,
                state=state,
                indicators=indicators,
            )

        monkeypatch.setattr(adapter, "submit_fraud_report", patched_submit_fraud_report)
        result = file_fraud_report_state_bureau_impl(
            "CLM-RETRY-STATE-001",
            "SIU-001",
            state="California",
            indicators='["staged"]',
        )
        data = json.loads(result)
        assert data["success"] is True
        assert data["report_id"].startswith("FRB-CA-")
        assert call_count == 3

    def test_file_nicb_report_persists(self, temp_db):
        """file_nicb_report_impl persists to fraud_report_filings."""
        from datetime import date

        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.observability import siu_workflow_scope
        from claim_agent.tools.siu_logic import file_nicb_report_impl

        repo = ClaimRepository()
        claim_id = repo.create_claim(
            ClaimInput(
                policy_number="POL-NICB",
                vin="VIN-NICB",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date=date(2026, 1, 15),
                incident_description="Vehicle theft",
                damage_description="Stolen",
                estimated_damage=15000,
            )
        )
        case_id = "SIU-MOCK-NICB"
        with siu_workflow_scope(claim_id=claim_id, case_id=case_id):
            result = file_nicb_report_impl(claim_id, case_id, "theft", '["theft"]')
        data = json.loads(result)
        assert data["success"] is True
        assert "NICB-" in data["report_id"]
        filings = repo.get_fraud_filings_for_claim(claim_id)
        nicb_filings = [f for f in filings if f["filing_type"] == "nicb"]
        assert len(nicb_filings) == 1
        assert nicb_filings[0]["report_id"] == data["report_id"]

    def test_file_niss_report_persists(self, temp_db):
        """file_niss_report_impl persists to fraud_report_filings."""
        from datetime import date

        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.observability import siu_workflow_scope
        from claim_agent.tools.siu_logic import file_niss_report_impl

        repo = ClaimRepository()
        claim_id = repo.create_claim(
            ClaimInput(
                policy_number="POL-NISS",
                vin="VIN-NISS",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date=date(2026, 1, 15),
                incident_description="Fraud",
                damage_description="Staged",
                estimated_damage=5000,
            )
        )
        case_id = "SIU-MOCK-NISS"
        with siu_workflow_scope(claim_id=claim_id, case_id=case_id):
            result = file_niss_report_impl(claim_id, case_id, "fraud", '["staged"]')
        data = json.loads(result)
        assert data["success"] is True
        assert "NISS-" in data["report_id"]
        filings = repo.get_fraud_filings_for_claim(claim_id)
        niss_filings = [f for f in filings if f["filing_type"] == "niss"]
        assert len(niss_filings) == 1
        assert niss_filings[0]["report_id"] == data["report_id"]
