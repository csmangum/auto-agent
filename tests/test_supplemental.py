"""Tests for supplemental claim workflow."""

import json
from unittest.mock import MagicMock, patch

import pytest

from claim_agent.db.constants import SUPPLEMENTABLE_STATUSES
from claim_agent.exceptions import ClaimNotFoundError


class TestSupplementalLogic:
    """Unit tests for supplemental logic in partial_loss_logic."""

    def test_get_original_repair_estimate_not_found(self):
        from claim_agent.tools.partial_loss_logic import get_original_repair_estimate_impl

        result = json.loads(get_original_repair_estimate_impl("CLM-NONEXISTENT"))
        assert "error" in result
        assert "not found" in result["error"].lower()

    def test_get_original_repair_estimate_no_partial_loss_workflow(self, seeded_temp_db):
        from claim_agent.tools.partial_loss_logic import get_original_repair_estimate_impl

        # CLM-TEST001 has new claim_type, not partial_loss
        result = json.loads(get_original_repair_estimate_impl("CLM-TEST001"))
        assert "error" in result
        assert "No partial loss workflow" in result["error"]

    def test_get_original_repair_estimate_found(self, seeded_temp_db):
        from claim_agent.tools.partial_loss_logic import get_original_repair_estimate_impl

        result = json.loads(get_original_repair_estimate_impl("CLM-TEST005"))
        assert "error" not in result
        assert result.get("total_estimate") == 2100.0
        assert result.get("parts_cost") == 550.0
        assert result.get("labor_cost") == 337.5
        assert result.get("shop_id") == "SHOP-001"
        assert result.get("authorization_id") == "RA-ABC12345"

    def test_calculate_supplemental_estimate_impl(self):
        from claim_agent.tools.partial_loss_logic import calculate_supplemental_estimate_impl

        result = json.loads(
            calculate_supplemental_estimate_impl(
                supplemental_damage_description="Hidden frame damage",
                vehicle_make="Toyota",
                vehicle_year=2022,
                policy_number="POL-005",
            )
        )
        assert "error" not in result
        assert result.get("is_supplemental") is True
        assert "total_estimate" in result
        assert "supplemental_damage_description" in result

    def test_update_repair_authorization_impl(self):
        from claim_agent.tools.partial_loss_logic import update_repair_authorization_impl

        result = json.loads(
            update_repair_authorization_impl(
                claim_id="CLM-TEST005",
                shop_id="SHOP-001",
                original_total=2100.0,
                original_parts=550.0,
                original_labor=337.5,
                original_insurance_pays=1600.0,
                supplemental_total=450.0,
                supplemental_parts=200.0,
                supplemental_labor=250.0,
                supplemental_insurance_pays=450.0,
            )
        )
        assert result["success"] is True
        assert result["combined_total"] == 2550.0
        assert result["combined_insurance_pays"] == 2050.0
        assert result["supplemental_authorization_id"].startswith("RA-SUP-")


class TestSupplementalTools:
    """Tests for supplemental tool wrappers."""

    def test_get_original_repair_estimate_tool(self, seeded_temp_db):
        from claim_agent.tools.supplemental_tools import get_original_repair_estimate

        result = get_original_repair_estimate.run(claim_id="CLM-TEST005")
        data = json.loads(result)
        assert data["total_estimate"] == 2100.0

    def test_calculate_supplemental_estimate_tool(self):
        from claim_agent.tools.supplemental_tools import calculate_supplemental_estimate

        result = calculate_supplemental_estimate.run(
            supplemental_damage_description="Frame damage",
            vehicle_make="Toyota",
            vehicle_year=2022,
            policy_number="POL-005",
        )
        data = json.loads(result)
        assert data.get("is_supplemental") is True

    def test_update_repair_authorization_tool(self):
        from claim_agent.tools.supplemental_tools import update_repair_authorization

        result = update_repair_authorization.run(
            claim_id="CLM-001",
            shop_id="SHOP-001",
            original_total=1000.0,
            original_parts=400.0,
            original_labor=300.0,
            original_insurance_pays=500.0,
            supplemental_total=200.0,
            supplemental_parts=100.0,
            supplemental_labor=100.0,
            supplemental_insurance_pays=200.0,
        )
        data = json.loads(result)
        assert data["combined_total"] == 1200.0


class TestSupplementalCrew:
    """Tests for supplemental crew structure."""

    def test_supplemental_crew_has_three_agents(self):
        from claim_agent.crews.supplemental_crew import create_supplemental_crew

        crew = create_supplemental_crew()
        assert len(crew.agents) == 3
        assert len(crew.tasks) == 3

    def test_supplemental_crew_task_inputs(self):
        from claim_agent.crews.supplemental_crew import create_supplemental_crew

        crew = create_supplemental_crew()
        task_descs = [t.description for t in crew.tasks]
        for desc in task_descs:
            assert "{claim_data}" in desc
            assert "{supplemental_data}" in desc
        # Tasks 2 and 3 use original_workflow_output
        assert "{original_workflow_output}" in task_descs[1]
        assert "{original_workflow_output}" in task_descs[2]


class TestSupplementalOrchestrator:
    """Tests for run_supplemental_workflow."""

    def test_run_supplemental_workflow_claim_not_found(self):
        from claim_agent.workflow.supplemental_orchestrator import run_supplemental_workflow

        with pytest.raises(ClaimNotFoundError, match="not found"):
            run_supplemental_workflow(
                {"claim_id": "CLM-NONEXISTENT", "supplemental_damage_description": "Frame damage"}
            )

    def test_run_supplemental_workflow_wrong_claim_type(self, seeded_temp_db):
        from claim_agent.workflow.supplemental_orchestrator import run_supplemental_workflow

        with pytest.raises(ValueError, match="partial_loss"):
            run_supplemental_workflow(
                {"claim_id": "CLM-TEST001", "supplemental_damage_description": "Frame damage"}
            )

    def test_run_supplemental_workflow_wrong_status(self, seeded_temp_db):
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.workflow.supplemental_orchestrator import run_supplemental_workflow

        repo = ClaimRepository()
        repo.update_claim_status("CLM-TEST005", "needs_review", details="Test")

        with pytest.raises(ValueError, match="cannot receive supplemental"):
            run_supplemental_workflow(
                {"claim_id": "CLM-TEST005", "supplemental_damage_description": "Frame damage"}
            )

    def test_run_supplemental_workflow_success(self, seeded_temp_db):
        from claim_agent.context import ClaimContext
        from claim_agent.workflow.supplemental_orchestrator import run_supplemental_workflow

        mock_result = MagicMock()
        mock_result.raw = (
            "Supplemental processed. supplemental_total: 450.00 "
            "combined_insurance_pays: 2050.00"
        )

        with patch("claim_agent.workflow.supplemental_orchestrator.get_llm"):
            with patch(
                "claim_agent.workflow.supplemental_orchestrator.create_supplemental_crew"
            ) as mock_crew_fn:
                mock_crew = MagicMock()
                mock_crew.kickoff.return_value = mock_result
                mock_crew_fn.return_value = mock_crew

                ctx = ClaimContext.from_defaults(db_path=seeded_temp_db)
                result = run_supplemental_workflow(
                    {
                        "claim_id": "CLM-TEST005",
                        "supplemental_damage_description": "Hidden frame damage",
                        "reported_by": "shop",
                    },
                    ctx=ctx,
                )

        assert result["claim_id"] == "CLM-TEST005"
        assert "workflow_output" in result
        assert "summary" in result
        assert result["supplemental_amount"] == 450.0
        assert result["combined_insurance_pays"] == 2050.0


class TestSupplementalExtractors:
    """Tests for amount extraction from workflow output."""

    def test_extract_supplemental_amount(self):
        from claim_agent.workflow.supplemental_orchestrator import _extract_supplemental_amount

        out = "supplemental_total: 450.00"
        assert _extract_supplemental_amount(out) == 450.0

    def test_extract_supplemental_amount_insurance_pays(self):
        from claim_agent.workflow.supplemental_orchestrator import _extract_supplemental_amount

        out = "supplemental_insurance_pays: 450"
        assert _extract_supplemental_amount(out) == 450.0

    def test_extract_supplemental_amount_none(self):
        from claim_agent.workflow.supplemental_orchestrator import _extract_supplemental_amount

        assert _extract_supplemental_amount("No amounts here") is None

    def test_extract_combined_insurance_pays(self):
        from claim_agent.workflow.supplemental_orchestrator import _extract_combined_insurance_pays

        out = "combined_insurance_pays: 2050.50"
        assert _extract_combined_insurance_pays(out) == 2050.5

    def test_extract_combined_insurance_pays_none(self):
        from claim_agent.workflow.supplemental_orchestrator import _extract_combined_insurance_pays

        assert _extract_combined_insurance_pays("No amounts") is None


class TestSupplementableStatuses:
    """Tests for SUPPLEMENTABLE_STATUSES constant."""

    def test_supplementable_statuses_contains_processing_and_settled(self):
        assert "processing" in SUPPLEMENTABLE_STATUSES
        assert "settled" in SUPPLEMENTABLE_STATUSES


class TestSupplementalToolsInit:
    """Tests for tools __init__ lazy loading."""

    def test_supplemental_tools_importable(self):
        from claim_agent.tools import (
            calculate_supplemental_estimate,
            get_original_repair_estimate,
            update_repair_authorization,
        )

        assert get_original_repair_estimate is not None
        assert calculate_supplemental_estimate is not None
        assert update_repair_authorization is not None
