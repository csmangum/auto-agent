#!/usr/bin/env python3
"""Evaluation script for standalone post-intake workflows.

Evaluates supplemental, dispute, denial/coverage, and handback workflows
with mocked LLMs for deterministic CI runs. Produces a JSON report.

Usage:
    python scripts/evaluate_standalone_workflows.py [--output PATH] [--verbose]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure src is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

os.environ.setdefault(
    "MOCK_DB_PATH",
    str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"),
)


@dataclass
class WorkflowScenarioResult:
    """Result of running a single workflow scenario."""

    workflow: str
    scenario_name: str
    success: bool
    error: str | None = None
    latency_ms: float = 0.0


def _seed_db_for_workflows(db_path: str) -> None:
    """Seed database with claims required for standalone workflow scenarios."""
    from claim_agent.db.database import get_connection, init_db

    init_db(db_path)
    with get_connection(db_path) as conn:
        # CLM-SUP01: partial_loss, processing (for supplemental)
        conn.execute(
            """INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "CLM-SUP01",
                "POL-001",
                "1HGBH41JXMN109186",
                2021,
                "Honda",
                "Accord",
                "2025-01-15",
                "Rear-ended",
                "Rear bumper damage",
                2500.0,
                "partial_loss",
                "processing",
            ),
        )
        partial_output = json.dumps({
            "total_estimate": 2100.0,
            "insurance_pays": 1600.0,
            "authorization_id": "RA-001",
        })
        conn.execute(
            """INSERT INTO workflow_runs (claim_id, claim_type, router_output, workflow_output)
            VALUES (?, ?, ?, ?)""",
            ("CLM-SUP01", "partial_loss", "partial_loss", partial_output),
        )

        # CLM-DIS01: new, open total_loss (for dispute)
        conn.execute(
            """INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "CLM-DIS01",
                "POL-002",
                "5YJSA1E26HF123456",
                2020,
                "Tesla",
                "Model 3",
                "2025-01-20",
                "Flood damage",
                "Submerged",
                45000.0,
                "total_loss",
                "open",
            ),
        )

        # CLM-DEN01: denied (for denial/coverage)
        conn.execute(
            """INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "CLM-DEN01",
                "POL-003",
                "3VWDX7AJ5DM999999",
                2019,
                "Volkswagen",
                "Jetta",
                "2025-01-22",
                "Staged accident",
                "Front bumper",
                35000.0,
                "fraud",
                "denied",
            ),
        )

        # CLM-HB01: needs_review (for handback)
        conn.execute(
            """INSERT INTO claims (id, policy_number, vin, vehicle_year, vehicle_make,
            vehicle_model, incident_date, incident_description, damage_description,
            estimated_damage, claim_type, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "CLM-HB01",
                "POL-004",
                "2HGFG3B54CH123456",
                2022,
                "Toyota",
                "Camry",
                "2025-01-25",
                "Minor scratch",
                "Minor scratch",
                500.0,
                "partial_loss",
                "needs_review",
            ),
        )


def _run_supplemental_scenario(db_path: str, verbose: bool) -> WorkflowScenarioResult:
    """Run supplemental workflow scenario with mocked LLM."""
    import time

    from claim_agent.context import ClaimContext
    from claim_agent.workflow.supplemental_orchestrator import run_supplemental_workflow

    start = time.perf_counter()
    try:
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

                ctx = ClaimContext.from_defaults(db_path=db_path)
                result = run_supplemental_workflow(
                    {
                        "claim_id": "CLM-SUP01",
                        "supplemental_damage_description": "Hidden frame damage",
                        "reported_by": "shop",
                    },
                    ctx=ctx,
                )

        success = (
            result.get("claim_id") == "CLM-SUP01"
            and result.get("supplemental_amount") == 450.0
            and result.get("combined_insurance_pays") == 2050.0
        )
        latency_ms = (time.perf_counter() - start) * 1000
        if verbose:
            print(f"  supplemental: {'PASS' if success else 'FAIL'} ({latency_ms:.0f}ms)")
        return WorkflowScenarioResult(
            workflow="supplemental",
            scenario_name="supplemental_success",
            success=success,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        if verbose:
            print(f"  supplemental: FAIL - {e}")
        return WorkflowScenarioResult(
            workflow="supplemental",
            scenario_name="supplemental_success",
            success=False,
            error=str(e)[:500],
            latency_ms=latency_ms,
        )


def _run_dispute_scenario(db_path: str, verbose: bool) -> WorkflowScenarioResult:
    """Run dispute workflow scenario (auto_resolve) with mocked LLM."""
    import time

    from claim_agent.context import ClaimContext
    from claim_agent.db.constants import STATUS_DISPUTE_RESOLVED
    from claim_agent.workflow.dispute_orchestrator import run_dispute_workflow

    start = time.perf_counter()
    try:
        mock_result = MagicMock()
        mock_result.raw = "Resolution: AUTO_RESOLVED. Adjusted amount: $16,000.00. Findings: ACV recalculated."

        with patch("claim_agent.workflow.dispute_orchestrator.get_llm"):
            with patch("claim_agent.workflow.dispute_orchestrator.create_dispute_crew") as mock_crew_fn:
                mock_crew = MagicMock()
                mock_crew.kickoff.return_value = mock_result
                mock_crew_fn.return_value = mock_crew

                ctx = ClaimContext.from_defaults(db_path=db_path)
                result = run_dispute_workflow(
                    {
                        "claim_id": "CLM-DIS01",
                        "dispute_type": "valuation_disagreement",
                        "dispute_description": "ACV is too low",
                    },
                    ctx=ctx,
                )
        # NOTE: run_dispute_workflow obtains its DB connection via ClaimContext,
        # which here is constructed using the explicit db_path argument passed into this function.
        success = (
            result.get("claim_id") == "CLM-DIS01"
            and result.get("resolution_type") == "auto_resolved"
            and result.get("status") == STATUS_DISPUTE_RESOLVED
        )
        latency_ms = (time.perf_counter() - start) * 1000
        if verbose:
            print(f"  dispute: {'PASS' if success else 'FAIL'} ({latency_ms:.0f}ms)")
        return WorkflowScenarioResult(
            workflow="dispute",
            scenario_name="dispute_auto_resolve",
            success=success,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        if verbose:
            print(f"  dispute: FAIL - {e}")
        return WorkflowScenarioResult(
            workflow="dispute",
            scenario_name="dispute_auto_resolve",
            success=False,
            error=str(e)[:500],
            latency_ms=latency_ms,
        )


def _run_denial_scenario(db_path: str, verbose: bool) -> WorkflowScenarioResult:
    """Run denial/coverage workflow scenario with mocked LLM."""
    import time

    from claim_agent.context import ClaimContext
    from claim_agent.workflow.denial_coverage_orchestrator import run_denial_coverage_workflow

    start = time.perf_counter()
    try:
        mock_result = MagicMock()
        mock_result.tasks_output = [
            MagicMock(output="Coverage analysis complete"),
            MagicMock(output="Denial letter generated"),
            MagicMock(output='{"outcome": "denial_upheld", "final_determination": "Denial upheld"}'),
        ]
        mock_result.raw = "Denial upheld. Letter generated."
        mock_result.output = "Denial upheld."

        with patch("claim_agent.workflow.denial_coverage_orchestrator.get_llm"):
            with patch(
                "claim_agent.workflow.denial_coverage_orchestrator.create_denial_coverage_crew"
            ) as mock_crew_fn:
                mock_crew = MagicMock()
                mock_crew.kickoff.return_value = mock_result
                mock_crew_fn.return_value = mock_crew

                ctx = ClaimContext.from_defaults(db_path=db_path)
                result = run_denial_coverage_workflow(
                    {"claim_id": "CLM-DEN01", "denial_reason": "Policy exclusion"},
                    ctx=ctx,
                )

        success = result.get("claim_id") == "CLM-DEN01" and "workflow_output" in result
        latency_ms = (time.perf_counter() - start) * 1000
        if verbose:
            print(f"  denial_coverage: {'PASS' if success else 'FAIL'} ({latency_ms:.0f}ms)")
        return WorkflowScenarioResult(
            workflow="denial_coverage",
            scenario_name="denial_upheld",
            success=success,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        if verbose:
            print(f"  denial_coverage: FAIL - {e}")
        return WorkflowScenarioResult(
            workflow="denial_coverage",
            scenario_name="denial_upheld",
            success=False,
            error=str(e)[:500],
            latency_ms=latency_ms,
        )


def _run_handback_scenario(db_path: str, verbose: bool) -> WorkflowScenarioResult:
    """Run handback workflow scenario with mocked crew and main workflow."""
    import time

    from claim_agent.context import ClaimContext
    from claim_agent.db.constants import STATUS_PROCESSING
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.workflow.handback_orchestrator import run_handback_workflow

    start = time.perf_counter()
    try:
        # Mock _kickoff_with_retry to transition claim to processing (simulates crew behavior)
        def fake_kickoff(crew, inputs):
            repo = ClaimRepository(db_path=db_path)
            repo.update_claim_status(
                "CLM-HB01",
                STATUS_PROCESSING,
                "Handback applied",
                claim_type="partial_loss",
                actor_id="handback_crew",
            )

        with patch(
            "claim_agent.workflow.handback_orchestrator.create_human_review_handback_crew"
        ) as mock_crew_fn:
            mock_crew_fn.return_value = MagicMock()

            with patch(
                "claim_agent.workflow.handback_orchestrator._kickoff_with_retry",
                side_effect=fake_kickoff,
            ):
                with patch(
                    "claim_agent.workflow.orchestrator.run_claim_workflow"
                ) as mock_main:
                    mock_main.return_value = {
                        "claim_id": "CLM-HB01",
                        "status": STATUS_PROCESSING,
                        "claim_type": "partial_loss",
                    }

                    ctx = ClaimContext.from_defaults(db_path=db_path)
                    result = run_handback_workflow(
                        "CLM-HB01",
                        reviewer_decision={"confirmed_claim_type": "partial_loss", "confirmed_payout": 2000},
                        actor_id="eval-test",
                        ctx=ctx,
                    )

        success = result.get("claim_id") == "CLM-HB01" and result.get("status") == STATUS_PROCESSING
        latency_ms = (time.perf_counter() - start) * 1000
        if verbose:
            print(f"  handback: {'PASS' if success else 'FAIL'} ({latency_ms:.0f}ms)")
        return WorkflowScenarioResult(
            workflow="handback",
            scenario_name="handback_success",
            success=success,
            latency_ms=latency_ms,
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start) * 1000
        if verbose:
            print(f"  handback: FAIL - {e}")
        return WorkflowScenarioResult(
            workflow="handback",
            scenario_name="handback_success",
            success=False,
            error=str(e)[:500],
            latency_ms=latency_ms,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate standalone workflows (supplemental, dispute, denial, handback)"
    )
    parser.add_argument("--output", help="Save report to JSON file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        os.environ["CLAIMS_DB_PATH"] = db_path
        _seed_db_for_workflows(db_path)

        results: list[WorkflowScenarioResult] = []

        if args.verbose:
            print("\nRunning standalone workflow scenarios...")

        results.append(_run_supplemental_scenario(db_path, args.verbose))
        results.append(_run_dispute_scenario(db_path, args.verbose))
        results.append(_run_denial_scenario(db_path, args.verbose))
        results.append(_run_handback_scenario(db_path, args.verbose))

        passed = sum(1 for r in results if r.success)
        total = len(results)
        report = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total_scenarios": total,
                "passed": passed,
                "failed": total - passed,
                "success_rate": passed / total if total else 0,
            },
            "by_workflow": {},
            "results": [
                {
                    "workflow": r.workflow,
                    "scenario": r.scenario_name,
                    "success": r.success,
                    "error": r.error,
                    "latency_ms": r.latency_ms,
                }
                for r in results
            ],
        }

        for r in results:
            if r.workflow not in report["by_workflow"]:
                report["by_workflow"][r.workflow] = {"total": 0, "passed": 0}
            report["by_workflow"][r.workflow]["total"] += 1
            if r.success:
                report["by_workflow"][r.workflow]["passed"] += 1

        print("\n" + "=" * 60)
        print("STANDALONE WORKFLOW EVALUATION REPORT")
        print("=" * 60)
        print(f"Total: {passed}/{total} passed ({report['summary']['success_rate']:.0%})")
        for r in results:
            status = "PASS" if r.success else "FAIL"
            print(f"  {r.workflow:20} {r.scenario_name:25} {status}")
        print("=" * 60)

        output_path = args.output or "standalone_workflow_report.json"
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {output_path}")

        return 0 if passed == total else 1
    finally:
        os.environ.pop("CLAIMS_DB_PATH", None)
        try:
            os.unlink(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
