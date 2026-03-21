"""Unit tests for FNOL coverage verification."""

import json
from datetime import date, datetime
from pathlib import Path
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
        """POL-008 has liability only; theft requires comprehensive -> deny."""
        claim_data = {
            "policy_number": "POL-008",
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
        with patch("claim_agent.workflow.coverage_verification.query_policy_db_impl") as mock:
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
        with patch("claim_agent.workflow.coverage_verification.get_coverage_config") as mock:
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
        with patch("claim_agent.workflow.coverage_verification.get_coverage_config") as mock:
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
        with patch("claim_agent.workflow.coverage_verification.get_coverage_config") as mock:
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
        with patch("claim_agent.workflow.coverage_verification.query_policy_db_impl") as mock:
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
        with patch("claim_agent.workflow.coverage_verification.query_policy_db_impl") as mock:
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


class TestTerritoryVerification:
    """Unit tests for policy territory verification."""

    def test_passes_with_incident_in_us_territory(self):
        """POL-001 has territory='US'; California incident passes."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "California",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert not result.denied
        assert result.details.get("territory_verified") is True

    def test_passes_with_state_code_in_us_territory(self):
        """POL-001 has territory='US'; TX state code passes."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "TX",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True

    def test_denies_incident_outside_us_territory(self):
        """POL-001 has territory='US'; Mexico incident denied."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "Mexico",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert not result.passed
        assert "outside" in result.reason.lower() or "territory" in result.reason.lower()
        assert result.details.get("incident_location") == "Mexico"
        assert result.details.get("policy_territory") == "US"

    def test_passes_with_incident_in_state_list_territory(self):
        """POL-100 has territory=['California', 'Nevada', 'Arizona']; Nevada passes."""
        claim_data = {
            "policy_number": "POL-100",
            "damage_description": "Collision damage",
            "estimated_damage": 500,
            "incident_location": "Nevada",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True

    def test_denies_incident_outside_state_list_territory(self):
        """POL-100 has territory=['California', 'Nevada', 'Arizona']; Texas denied."""
        claim_data = {
            "policy_number": "POL-100",
            "damage_description": "Collision damage",
            "estimated_damage": 500,
            "incident_location": "Texas",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert "outside" in result.reason.lower() or "territory" in result.reason.lower()
        assert "California, Nevada, Arizona" in result.reason

    def test_denies_incident_in_excluded_territory(self):
        """POL-003 has excluded_territories=['Alaska', 'Hawaii']; Alaska denied."""
        claim_data = {
            "policy_number": "POL-003",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "Alaska",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert "excluded" in result.reason.lower()
        assert result.details.get("excluded_territories") == ["Alaska", "Hawaii"]

    def test_passes_when_not_in_excluded_and_in_territory(self):
        """POL-003 has territory='US' but excludes Alaska/Hawaii; California passes."""
        claim_data = {
            "policy_number": "POL-003",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "California",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True

    def test_passes_with_usa_canada_territory(self):
        """POL-004 has territory='USA_Canada'; Canada incident passes."""
        claim_data = {
            "policy_number": "POL-004",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "Canada",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True

    def test_passes_with_usa_canada_territory_us_state(self):
        """POL-004 has territory='USA_Canada'; New York incident passes."""
        claim_data = {
            "policy_number": "POL-004",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "New York",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True

    def test_passes_when_no_territory_restriction(self):
        """Policy without territory field passes regardless of location."""
        claim_data = {
            "policy_number": "POL-005",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "Japan",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is None

    def test_passes_when_incident_location_not_provided_and_no_config_requirement(self):
        """No incident_location and no require_incident_location config -> passes."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_under_investigation_when_location_missing_and_required(self):
        """When require_incident_location=True and location missing -> under_investigation."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
        }
        with patch("claim_agent.workflow.coverage_verification.get_coverage_config") as mock:
            mock.return_value = {
                "enabled": True,
                "require_incident_location": True,
            }
            ctx = _ctx_with_mock_db(":memory:")
            result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.under_investigation
        assert (
            "location required" in result.reason.lower()
            or "territory verification" in result.reason.lower()
        )

    def test_uses_loss_state_as_fallback_for_incident_location(self):
        """When incident_location missing but loss_state present, uses loss_state."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "loss_state": "Florida",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True
        assert result.details.get("incident_location") == "Florida"

    def test_case_insensitive_territory_matching(self):
        """Territory matching is case-insensitive (california == California)."""
        claim_data = {
            "policy_number": "POL-100",
            "damage_description": "Collision damage",
            "estimated_damage": 500,
            "incident_location": "california",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_state_code_matches_state_name_territory(self):
        """incident_location='NV' (code) matches territory='Nevada' (name) in list."""
        claim_data = {
            "policy_number": "POL-100",
            "damage_description": "Collision damage",
            "estimated_damage": 500,
            "incident_location": "NV",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_state_name_matches_state_code_in_excluded_territory(self):
        """incident_location='Alaska' (name) matches excluded='AK' (code)."""
        # POL-003 excludes Alaska and Hawaii by full name; verify AK code is also excluded
        claim_data = {
            "policy_number": "POL-003",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "AK",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert "excluded" in result.reason.lower()

    def test_state_code_in_excluded_territory_blocks_state_name_incident(self):
        """POL-101 excludes 'AK'/'HI' as codes; incident_location='Alaska' (name) is denied."""
        claim_data = {
            "policy_number": "POL-101",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "Alaska",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert "excluded" in result.reason.lower()

    def test_district_of_columbia_passes_us_territory_casefold(self):
        """DC full name must match US territory without .title() artifacts."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "district of columbia",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True

    def test_exclusions_enforced_when_no_positive_territory(self):
        """POL-EXCL-ONLY has excluded_territories only; Florida denied, Texas passes."""
        ctx = _ctx_with_mock_db(":memory:")
        denied = verify_coverage_impl(
            {
                "policy_number": "POL-EXCL-ONLY",
                "damage_description": "Collision damage",
                "estimated_damage": 2000,
                "incident_location": "Florida",
            },
            ctx=ctx,
        )
        assert denied.denied
        assert "excluded" in denied.reason.lower()

        ok = verify_coverage_impl(
            {
                "policy_number": "POL-EXCL-ONLY",
                "damage_description": "Collision damage",
                "estimated_damage": 2000,
                "incident_location": "Texas",
            },
            ctx=ctx,
        )
        assert ok.passed
        assert ok.details.get("territory_verified") is True
        assert ok.details.get("incident_location") == "Texas"

    def test_passes_puerto_rico_under_us_territory(self):
        """territory='US' includes US insular areas (e.g. Puerto Rico / PR)."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "Puerto Rico",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True

    def test_passes_pr_code_under_us_territory(self):
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "PR",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_passes_ontario_under_usa_canada_territory(self):
        """USA_Canada matches Canadian provinces by name or code."""
        claim_data = {
            "policy_number": "POL-004",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "Ontario",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("territory_verified") is True

    def test_passes_on_code_under_usa_canada_territory(self):
        claim_data = {
            "policy_number": "POL-004",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "ON",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_require_incident_location_when_policy_has_only_exclusions(self):
        """Missing location escalates when excluded_territories set but territory absent."""
        claim_data = {
            "policy_number": "POL-EXCL-ONLY",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
        }
        with patch("claim_agent.workflow.coverage_verification.get_coverage_config") as mock:
            mock.return_value = {
                "enabled": True,
                "require_incident_location": True,
            }
            ctx = _ctx_with_mock_db(":memory:")
            result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.under_investigation
        assert result.details.get("excluded_territories") == ["Florida"]
        assert (
            "location required" in result.reason.lower()
            or "territory verification" in result.reason.lower()
        )

    def test_whitespace_only_incident_location_treated_as_missing(self):
        """Whitespace-only location does not run territory deny path; can trigger require."""
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "   \t",
        }
        with patch("claim_agent.workflow.coverage_verification.get_coverage_config") as mock:
            mock.return_value = {
                "enabled": True,
                "require_incident_location": True,
            }
            ctx = _ctx_with_mock_db(":memory:")
            result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.under_investigation

    def test_under_investigation_when_territory_list_has_non_strings(self):
        """Non-string entries in territory list -> config_error, not workflow crash."""
        import json as json_module

        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_location": "California",
        }
        fake_policy = {
            "valid": True,
            "status": "active",
            "physical_damage_covered": True,
            "physical_damage_coverages": ["collision", "comprehensive"],
            "deductible": 500,
            "territory": ["CA", 99],
        }
        with patch("claim_agent.workflow.coverage_verification.query_policy_db_impl") as mock:
            mock.return_value = json_module.dumps(fake_policy)
            result = verify_coverage_impl(claim_data, ctx=None)
        assert result.under_investigation
        assert result.details.get("territory_verification") == "config_error"


class TestPolicyTermVerification:
    """Incident date vs policy effective/expiration (issue #257)."""

    def test_passes_with_incident_within_default_term(self):
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_date": "2025-06-15",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("term_verified") is True
        assert result.details.get("incident_date") == "2025-06-15"

    def test_datetime_incident_date_accepted(self):
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_date": datetime(2025, 6, 15, 14, 30, 0),
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("term_verified") is True
        assert result.details.get("incident_date") == "2025-06-15"

    def test_date_incident_date_accepted(self):
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_date": date(2025, 6, 15),
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed

    def test_skips_term_when_no_incident_date(self):
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.passed
        assert result.details.get("term_verified") is None

    def test_denies_after_policy_expiration(self):
        claim_data = {
            "policy_number": "POL-TERM-EXPIRED",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_date": "2025-01-20",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert "after" in result.reason.lower() or "expiration" in result.reason.lower()
        assert result.details.get("term_verification") == "after_expiration"

    def test_denies_before_policy_effective(self):
        claim_data = {
            "policy_number": "POL-TERM-EXPIRED",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_date": "2019-07-01",
        }
        ctx = _ctx_with_mock_db(":memory:")
        result = verify_coverage_impl(claim_data, ctx=ctx)
        assert result.denied
        assert "before" in result.reason.lower() or "effective" in result.reason.lower()
        assert result.details.get("term_verification") == "before_effective"

    def test_inclusive_boundaries_on_fixed_term_policy(self):
        ctx = _ctx_with_mock_db(":memory:")
        on_effective = verify_coverage_impl(
            {
                "policy_number": "POL-TERM-EXPIRED",
                "damage_description": "Collision damage",
                "estimated_damage": 2000,
                "incident_date": "2020-01-01",
            },
            ctx=ctx,
        )
        assert on_effective.passed
        on_exp = verify_coverage_impl(
            {
                "policy_number": "POL-TERM-EXPIRED",
                "damage_description": "Collision damage",
                "estimated_damage": 2000,
                "incident_date": "2024-06-01",
            },
            ctx=ctx,
        )
        assert on_exp.passed

    def test_under_investigation_when_only_one_term_field(self):
        import json as json_module

        fake_policy = {
            "valid": True,
            "status": "active",
            "physical_damage_covered": True,
            "physical_damage_coverages": ["collision", "comprehensive"],
            "deductible": 500,
            "effective_date": "2020-01-01",
        }
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_date": "2025-01-01",
        }
        with patch("claim_agent.workflow.coverage_verification.query_policy_db_impl") as mock:
            mock.return_value = json_module.dumps(fake_policy)
            result = verify_coverage_impl(claim_data, ctx=None)
        assert result.under_investigation
        assert result.details.get("error") == "policy_term_config"

    def test_under_investigation_when_incident_unparseable(self):
        import json as json_module

        fake_policy = {
            "valid": True,
            "status": "active",
            "physical_damage_covered": True,
            "physical_damage_coverages": ["collision", "comprehensive"],
            "deductible": 500,
            "effective_date": "2020-01-01",
            "expiration_date": "2030-01-01",
        }
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_date": "not-a-date",
        }
        with patch("claim_agent.workflow.coverage_verification.query_policy_db_impl") as mock:
            mock.return_value = json_module.dumps(fake_policy)
            result = verify_coverage_impl(claim_data, ctx=None)
        assert result.under_investigation
        assert result.details.get("term_verification") == "incident_unparseable"

    def test_under_investigation_when_term_dates_malformed(self):
        import json as json_module

        fake_policy = {
            "valid": True,
            "status": "active",
            "physical_damage_covered": True,
            "physical_damage_coverages": ["collision", "comprehensive"],
            "deductible": 500,
            "effective_date": "2020-01-01",
            "expiration_date": "bogus",
        }
        claim_data = {
            "policy_number": "POL-001",
            "damage_description": "Collision damage",
            "estimated_damage": 2000,
            "incident_date": "2025-01-01",
        }
        with patch("claim_agent.workflow.coverage_verification.query_policy_db_impl") as mock:
            mock.return_value = json_module.dumps(fake_policy)
            result = verify_coverage_impl(claim_data, ctx=None)
        assert result.under_investigation
        assert result.details.get("error") == "policy_term_parse"


class TestMockDbJson:
    """Smoke tests: data/mock_db.json parses; territory fixtures match tests."""

    def test_mock_db_json_parses_and_territory_policies_present(self):
        mock_path = Path(__file__).resolve().parents[1] / "data" / "mock_db.json"
        data = json.loads(mock_path.read_text(encoding="utf-8"))
        policies = data["policies"]
        for pid in (
            "POL-001",
            "POL-003",
            "POL-004",
            "POL-005",
            "POL-100",
            "POL-101",
            "POL-EXCL-ONLY",
        ):
            assert pid in policies, f"missing policy {pid}"
        assert policies["POL-001"].get("territory") == "US"
        assert policies["POL-003"].get("territory") == "US"
        assert policies["POL-003"].get("excluded_territories") == ["Alaska", "Hawaii"]
        assert policies["POL-004"].get("territory") == "USA_Canada"
        assert "territory" not in policies["POL-005"]
        assert policies["POL-100"].get("territory") == ["California", "Nevada", "Arizona"]
        assert policies["POL-101"].get("territory") == "US"
        assert policies["POL-101"].get("excluded_territories") == ["AK", "HI"]
        excl = policies["POL-EXCL-ONLY"]
        assert excl.get("territory") is None
        assert excl.get("excluded_territories") == ["Florida"]
        assert "POL-TERM-EXPIRED" in policies
        assert policies["POL-TERM-EXPIRED"]["expiration_date"] == "2024-06-01"
        assert data["_meta"].get("policy_term_defaults", {}).get("effective_date") == "2020-01-01"

    def test_load_mock_db_merges_policy_term_defaults(self):
        from claim_agent.data.loader import load_mock_db

        db = load_mock_db()
        assert db["policies"]["POL-001"]["effective_date"] == "2020-01-01"
        assert db["policies"]["POL-001"]["expiration_date"] == "2030-12-31"
        assert db["policies"]["POL-TERM-EXPIRED"]["expiration_date"] == "2024-06-01"

    def test_merge_policy_term_defaults_empty_string_counts_as_missing(self):
        """Whitespace-only term fields should not block _meta.policy_term_defaults merge."""
        from claim_agent.data.loader import _merge_policy_term_defaults

        data: dict = {
            "_meta": {
                "policy_term_defaults": {
                    "effective_date": "2020-01-01",
                    "expiration_date": "2030-01-01",
                }
            },
            "policies": {
                "P-EMPTY": {
                    "effective_date": "",
                    "expiration_date": "   ",
                    "term_start": "\t",
                    "term_end": "",
                }
            },
        }
        _merge_policy_term_defaults(data)
        pol = data["policies"]["P-EMPTY"]
        assert pol["effective_date"] == "2020-01-01"
        assert pol["expiration_date"] == "2030-01-01"


class TestCoverageStageIntegration:
    """Integration-style tests: coverage stage denies before router runs."""

    @pytest.mark.integration
    def test_workflow_denies_coverage_before_router(self, integration_db, mock_llm_instance):
        """Claim with POL-008 + theft is denied at coverage stage; router never runs."""
        from claim_agent.crews.main_crew import run_claim_workflow

        claim_data = {
            "policy_number": "POL-008",
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
        assert (
            "denied" in result.get("workflow_output", "").lower()
            or "coverage" in result.get("summary", "").lower()
        )

        repo = ClaimRepository(db_path=integration_db)
        claim = repo.get_claim(result["claim_id"])
        assert claim is not None
        assert claim["status"] == STATUS_DENIED
