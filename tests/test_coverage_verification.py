"""Unit tests for FNOL coverage verification."""

from unittest.mock import patch

import pytest

from claim_agent.context import ClaimContext
from claim_agent.db.constants import STATUS_DENIED
from claim_agent.db.repository import ClaimRepository
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
