"""Unit tests for FNOL coverage verification."""

from unittest.mock import patch

import pytest

from claim_agent.context import ClaimContext
from claim_agent.db.constants import STATUS_DENIED
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.stage_outputs import CoverageVerificationResult
from claim_agent.workflow.coverage_verification import verify_coverage_impl


def _ctx_with_mock_db(db_path: str) -> ClaimContext:
    """Build ClaimContext with mock policy adapter using given db path."""
    return ClaimContext.from_defaults(db_path=db_path)


class TestVerifyCoverageImpl:
    """Unit tests for verify_coverage_impl."""

    def test_passes_with_active_policy_and_collision_coverage(self):
        """POL-001 has collision+comprehensive; collision damage passes."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Front bumper collision",
            "estimated_damage": 2000,
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert not result.denied
        assert not result.under_investigation
        assert "Coverage verified" in result.reason

    def test_passes_with_theft_and_comprehensive(self):
        """POL-001 has comprehensive; theft damage passes."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Vehicle stolen",
            "estimated_damage": 30000,
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert not result.denied

    def test_denies_when_liability_only_and_theft(self):
        """POL-002 has liability only; theft requires comprehensive -> deny."""
        claim_data = {
            "policy_number": "POL-002",
            "damage_description": "Theft - vehicle stolen",
            "estimated_damage": 45000,
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert not result.passed
        assert "not covered" in result.reason.lower() or "comprehensive" in result.reason.lower()

    def test_denies_when_policy_inactive(self):
        """POL-021 is inactive -> deny."""
        claim_data = {
            "policy_number": "POL-021",
            "damage_description": "Front bumper collision",
            "estimated_damage": 2000,
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert "inactive" in result.reason.lower() or "not found" in result.reason.lower()

    def test_denies_when_policy_cancelled(self):
        """POL-025 is cancelled -> deny."""
        claim_data = {
            "policy_number": "POL-025",
            "damage_description": "Collision damage",
            "estimated_damage": 3000,
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied

    def test_denies_when_missing_policy_number(self):
        """Empty or missing policy number -> deny."""
        result = verify_coverage_impl({"policy_number": ""}, ctx=None)
        assert result.denied
        assert "policy" in result.reason.lower()

        result2 = verify_coverage_impl({"policy_number": "   "}, ctx=None)
        assert result2.denied

    def test_denies_when_policy_number_not_string(self):
        """Non-string policy_number (e.g. int) -> deny; details do not expose raw value."""
        result = verify_coverage_impl({"policy_number": 12345}, ctx=None)
        assert result.denied
        assert "policy" in result.reason.lower() or "invalid" in result.reason.lower()
        # Details should not expose full raw value inappropriately
        assert "policy_number" in result.details
        assert len(str(result.details["policy_number"])) <= 20

    def test_under_investigation_when_adapter_error(self):
        """Adapter error -> under_investigation."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision",
        }
        with patch(
            "claim_agent.workflow.coverage_verification.query_policy_db_impl"
        ) as mock:
            from claim_agent.exceptions import AdapterError
            mock.side_effect = AdapterError("Policy lookup failed")
            result = verify_coverage_impl(claim_data, ctx=None)
        assert result.under_investigation
        assert not result.passed
        assert not result.denied
        assert "manual review" in result.reason.lower() or "lookup" in result.reason.lower()

    def test_disabled_returns_passed(self):
        """When coverage verification disabled, returns passed."""
        claim_data = {"policy_number": "POL-001", "damage_description": "Collision"}
        with patch(
            "claim_agent.workflow.coverage_verification.get_coverage_config"
        ) as mock:
            mock.return_value = {"enabled": False}
            result = verify_coverage_impl(claim_data, ctx=None)
        assert result.passed
        assert "disabled" in result.reason.lower()

    def test_deny_when_deductible_exceeds_damage_if_configured(self):
        """When deny_when_deductible_exceeds_damage=True and deductible >= damage -> deny."""
        claim_data = {
            "policy_number": "POL-007",
            "damage_description": "Minor scratch",
            "estimated_damage": 500,
        }
        with patch(
            "claim_agent.workflow.coverage_verification.get_coverage_config"
        ) as mock:
            mock.return_value = {
                "enabled": True,
                "deny_when_deductible_exceeds_damage": True,
            }
            ctx = _ctx_with_mock_db(":memory:")
            result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert "deductible" in result.reason.lower()

    def test_under_investigation_when_deductible_parse_fails(self):
        """When deductible/damage parse fails -> under_investigation."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision",
            "estimated_damage": "N/A",
        }
        with patch(
            "claim_agent.workflow.coverage_verification.get_coverage_config"
        ) as mock:
            mock.return_value = {
                "enabled": True,
                "deny_when_deductible_exceeds_damage": True,
            }
            ctx = _ctx_with_mock_db(":memory:")
            result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.under_investigation
        assert not result.passed
        assert not result.denied
        assert "manual review" in result.reason.lower() or "compare" in result.reason.lower()
        assert result.details.get("error") == "parse_error"

    def test_estimated_damage_accepts_int_float_string_numeric(self):
        """estimated_damage as int, float, or string numeric parses correctly."""
        ctx = _ctx_with_mock_db(":memory:")
        base = {
            "policy_number": "POL-001",
            "damage_description": "Collision",
        }
        # int: passes (POL-001 deductible 500 < 2000)
        r1 = verify_coverage_impl({**base, "estimated_damage": 2000}, ctx=ctx)
        assert r1.passed
        # float: passes
        r2 = verify_coverage_impl({**base, "estimated_damage": 2000.0}, ctx=ctx)
        assert r2.passed
        # string numeric: passes
        r3 = verify_coverage_impl({**base, "estimated_damage": "2000"}, ctx=ctx)
        assert r3.passed

    def test_passes_when_claimant_is_named_insured(self):
        """Claimant matching named insured passes verification."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {
                    "party_type": "claimant",
                    "name": "John Doe",
                    "role": "driver",
                }
            ],
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert not result.denied
        assert not result.under_investigation

    def test_passes_when_claimant_is_authorized_driver(self):
        """Claimant matching authorized driver (but not named insured) passes verification."""
        claim_data = {
            "policy_number": "POL-003",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {
                    "party_type": "claimant",
                    "name": "Sarah Johnson",
                    "role": "driver",
                }
            ],
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert not result.denied
        assert not result.under_investigation

    def test_under_investigation_when_claimant_not_on_policy(self):
        """Claimant not matching named insured or drivers -> under_investigation."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {
                    "party_type": "claimant",
                    "name": "Unknown Driver",
                    "role": "driver",
                }
            ],
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.under_investigation
        assert not result.passed
        assert not result.denied
        assert "not listed" in result.reason.lower() or "driver" in result.reason.lower()

    def test_passes_when_claimant_name_missing(self):
        """Missing claimant name passes (legacy claims without claimant data)."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert not result.under_investigation

    def test_name_matching_case_insensitive(self):
        """Name matching is case-insensitive and whitespace-tolerant."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {
                    "party_type": "claimant",
                    "name": "  JOHN DOE  ",
                    "role": "driver",
                }
            ],
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_claimant_name_fallback_to_direct_field(self):
        """Falls back to claimant_name field if parties not provided."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "claimant_name": "John Doe",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_parties_none_treated_as_empty(self):
        """parties=None should be treated as empty (no TypeError), falling back to claimant_name."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": None,
            "claimant_name": "John Doe",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_non_string_party_type_is_safe(self):
        """party_type that is not a string (e.g. None) should not raise."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {"party_type": None, "name": "John Doe"},
                {"party_type": 42, "name": "Other"},
            ],
            "claimant_name": "John Doe",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_passes_full_name_display_name_via_real_policy_query_path(self):
        """POL-FULLNAME-TEST uses full_name/display_name in mock_db; real query_policy_db_impl path."""
        claim_data = {
            "policy_number": "POL-FULLNAME-TEST",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {"party_type": "claimant", "name": "Alex Alternate", "role": "driver"},
            ],
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert not result.denied
        assert not result.under_investigation

    def test_under_investigation_details_contain_no_pii(self):
        """Under-investigation result should not include email/phone/license in details."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {"party_type": "claimant", "name": "Unknown Driver"},
            ],
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.under_investigation
        details = result.details or {}
        # named_insured and drivers in details should be plain name strings, not dicts with PII.
        for person_list in (details.get("named_insured", []), details.get("drivers", [])):
            for person in person_list:
                assert isinstance(person, str), (
                    f"Expected name string in details, got {type(person).__name__}: {person!r}"
                )

    def test_name_key_variations_full_name_and_display_name(self):
        """Custom PolicyAdapter returning full_name or display_name should verify correctly."""
        import json

        # Test 1: Claimant matches named_insured via full_name
        claim_data1 = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {"party_type": "claimant", "name": "John Doe"},
            ],
        }
        policy_response1 = {
            "valid": True,
            "status": "active",
            "physical_damage_covered": True,
            "physical_damage_coverages": ["collision", "comprehensive"],
            "deductible": 500,
            "named_insured": [{"full_name": "John Doe", "email": "john@example.com"}],
            "drivers": [{"display_name": "Jane Doe", "phone": "555-1234"}],
        }
        with patch(
            "claim_agent.workflow.coverage_verification.query_policy_db_impl"
        ) as mock:
            mock.return_value = json.dumps(policy_response1)
            result1 = verify_coverage_impl(claim_data1, ctx=None)
        assert result1.passed
        assert not result1.under_investigation

        # Test 2: Claimant matches driver via display_name
        claim_data2 = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "parties": [
                {"party_type": "claimant", "name": "Jane Doe"},
            ],
        }
        with patch(
            "claim_agent.workflow.coverage_verification.query_policy_db_impl"
        ) as mock:
            mock.return_value = json.dumps(policy_response1)
            result2 = verify_coverage_impl(claim_data2, ctx=None)
        assert result2.passed
        assert not result2.under_investigation


class TestCoverageVerificationResult:
    """Tests for CoverageVerificationResult model invariants."""

    def test_exactly_one_outcome_required(self):
        """Model requires exactly one of passed/denied/under_investigation."""
        with pytest.raises(ValueError, match="Exactly one"):
            CoverageVerificationResult()
        with pytest.raises(ValueError, match="Exactly one"):
            CoverageVerificationResult(passed=True, denied=True)

    def test_valid_single_outcome(self):
        """Valid combinations pass validation."""
        CoverageVerificationResult(passed=True)
        CoverageVerificationResult(denied=True)
        CoverageVerificationResult(under_investigation=True)


class TestCoverageStageIntegration:
    """Integration-style tests: coverage stage denies before router runs."""

    @pytest.mark.integration
    def test_workflow_denies_coverage_before_router(
        self, integration_db, mock_llm_instance
    ):
        """Claim with POL-002 + theft is denied at coverage stage; router never runs."""
        from claim_agent.crews.main_crew import run_claim_workflow

        claim_data = {
            "policy_number": "POL-002",
            "vin": "5YJSA1E26HF123456",
            "vehicle_year": 2022,
            "vehicle_make": "Tesla",
            "vehicle_model": "Model 3",
            "incident_date": "2025-01-20",
            "incident_description": "Vehicle stolen.",
            "damage_description": "Theft - vehicle stolen overnight.",
            "estimated_damage": 45000,
        }

        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            mock_llm.return_value = mock_llm_instance
            result = run_claim_workflow(claim_data)

        assert result["status"] == STATUS_DENIED
        assert "claim_id" in result
        assert "denied" in result.get("workflow_output", "").lower() or "coverage" in result.get("summary", "").lower()

        repo = ClaimRepository(db_path=integration_db)
        claim = repo.get_claim(result["claim_id"])
        assert claim is not None
        assert claim["status"] == STATUS_DENIED
