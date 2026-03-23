"""Tests for the standalone workflow evaluation script.

Verifies the script runs successfully and produces valid reports.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
_project_root = Path(__file__).resolve().parent.parent


def _run_eval(args=None):
    env = os.environ.copy()
    env.setdefault("MOCK_DB_PATH", str(_project_root / "data" / "mock_db.json"))
    cmd = [sys.executable, str(_scripts_dir / "evaluate_standalone_workflows.py")]
    if args:
        cmd.extend(args)
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=_project_root,
        env=env,
    )


@pytest.mark.slow
def test_standalone_workflow_eval_script_runs(tmp_path):
    """Standalone workflow eval script should complete and exit 0."""
    report_path = tmp_path / "report.json"
    result = _run_eval(["--output", str(report_path)])
    assert result.returncode == 0, f"Script failed: {result.stderr}"


@pytest.mark.slow
def test_standalone_workflow_eval_produces_valid_report(tmp_path):
    """Standalone workflow eval should produce valid JSON report."""
    report_path = tmp_path / "report.json"
    result = _run_eval(["--output", str(report_path)])
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    assert report_path.exists()

    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)

    assert "timestamp" in report
    assert "summary" in report
    assert report["summary"]["total_scenarios"] == 4
    assert report["summary"]["passed"] == 4
    assert report["summary"]["success_rate"] == 1.0
    assert "results" in report
    assert len(report["results"]) == 4

    workflows = {r["workflow"] for r in report["results"]}
    assert workflows == {"supplemental", "dispute", "denial_coverage", "handback"}

    for r in report["results"]:
        assert r.get("db_assertions_passed", True), (
            f"{r['workflow']}: DB assertions failed: {r.get('db_assertion_error', 'unknown')}"
        )
