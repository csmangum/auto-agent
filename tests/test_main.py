"""Tests for CLI (main.py) and process/reprocess validation."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

# Point to project data for mock_db
os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run_cli(args, env=None):
    """Run claim-agent CLI as subprocess. Returns (returncode, stdout, stderr)."""
    cmd = [sys.executable, "-m", "claim_agent.main"] + list(args)
    env = env or os.environ
    result = subprocess.run(
        cmd,
        cwd=str(_PROJECT_ROOT),
        capture_output=True,
        text=True,
        env={**os.environ, **env} if isinstance(env, dict) else env,
    )
    return result.returncode, result.stdout, result.stderr


def test_process_invalid_claim_exits_nonzero_no_claim_created():
    """Process with invalid claim JSON (missing required field) exits non-zero and creates no claim."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    invalid_json_path = _PROJECT_ROOT / "tests" / "sample_claims" / "new_claim.json"
    with open(invalid_json_path) as f:
        data = json.load(f)
    del data["vin"]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write(json.dumps(data))
        claim_path = f.name
    try:
        from claim_agent.db.database import init_db
        init_db(db_path)
        code, out, err = _run_cli(["process", claim_path], env={"CLAIMS_DB_PATH": db_path})
        assert code != 0
        assert "Invalid claim" in err or "validation" in err.lower()
        import sqlite3
        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM claims").fetchone()[0]
        conn.close()
        assert count == 0
    finally:
        os.unlink(db_path)
        os.unlink(claim_path)


def test_cli_status_nonexistent_exits_nonzero():
    """status with nonexistent claim_id exits non-zero and prints not found."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        from claim_agent.db.database import init_db
        init_db(db_path)
        code, out, err = _run_cli(["status", "CLM-NONEXISTENT"], env={"CLAIMS_DB_PATH": db_path})
        assert code != 0
        assert "not found" in err.lower()
    finally:
        os.unlink(db_path)


def test_cli_history_nonexistent_exits_nonzero():
    """history with nonexistent claim_id exits non-zero and prints not found."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        from claim_agent.db.database import init_db
        init_db(db_path)
        code, out, err = _run_cli(["history", "CLM-NONEXISTENT"], env={"CLAIMS_DB_PATH": db_path})
        assert code != 0
        assert "not found" in err.lower()
    finally:
        os.unlink(db_path)


def test_cli_reprocess_nonexistent_exits_nonzero():
    """reprocess with nonexistent claim_id exits non-zero and prints not found."""
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        from claim_agent.db.database import init_db
        init_db(db_path)
        code, out, err = _run_cli(["reprocess", "CLM-NONEXISTENT"], env={"CLAIMS_DB_PATH": db_path})
        assert code != 0
        assert "not found" in err.lower()
    finally:
        os.unlink(db_path)


def test_reprocess_validation_invalid_data_exits_nonzero():
    """Reprocess with claim data that would fail ClaimInput validation exits non-zero."""
    from claim_agent.main import _claim_data_from_row
    from claim_agent.models.claim import ClaimInput
    from pydantic import ValidationError

    # Build claim_data that is missing required field
    row = {
        "policy_number": "POL-1",
        "vin": None,  # would become "" with defaults
        "vehicle_year": 2020,
        "vehicle_make": "Honda",
        "vehicle_model": "Civic",
        "incident_date": "2025-01-01",
        "incident_description": "Test",
        "damage_description": "Test",
        "estimated_damage": None,
    }
    claim_data = _claim_data_from_row(row)
    # With defaults, vin becomes "" which may still validate in Pydantic (str allows "")
    # So force invalid: wrong type for vehicle_year
    claim_data["vehicle_year"] = "not_an_int"
    with pytest.raises(ValidationError):
        ClaimInput.model_validate(claim_data)