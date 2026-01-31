"""Integration tests for crews (require LLM; can be skipped if no API key)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))

# Skip crew tests if no OpenAI/OpenRouter key (avoid failing in CI without key)
SKIP_CREW = not os.environ.get("OPENAI_API_KEY")


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_new_claim_crew_kickoff():
    """Run new claim crew on sample input (requires LLM)."""
    from claim_agent.crews.new_claim_crew import create_new_claim_crew

    with open(Path(__file__).parent / "sample_claims" / "new_claim.json") as f:
        claim_data = json.load(f)

    crew = create_new_claim_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = crew.kickoff(inputs=inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output
    assert "CLM-" in str(output) or "claim" in str(output).lower()


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_duplicate_crew_kickoff():
    """Run duplicate crew on sample input (requires LLM)."""
    from claim_agent.crews.duplicate_crew import create_duplicate_crew

    with open(Path(__file__).parent / "sample_claims" / "duplicate_claim.json") as f:
        claim_data = json.load(f)

    crew = create_duplicate_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = crew.kickoff(inputs=inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_total_loss_crew_kickoff():
    """Run total loss crew on sample input (requires LLM)."""
    from claim_agent.crews.total_loss_crew import create_total_loss_crew

    with open(Path(__file__).parent / "sample_claims" / "total_loss_claim.json") as f:
        claim_data = json.load(f)

    crew = create_total_loss_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = crew.kickoff(inputs=inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output


def test_run_claim_workflow_classification_only():
    """Test that run_claim_workflow returns expected keys and persists to DB."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.database import init_db

    with open(Path(__file__).parent / "sample_claims" / "new_claim.json") as f:
        claim_data = json.load(f)

    if SKIP_CREW:
        pytest.skip("OPENAI_API_KEY not set")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        result = run_claim_workflow(claim_data)
        assert "claim_id" in result
        assert "claim_type" in result
        assert result["claim_type"] in ("new", "duplicate", "total_loss")
        assert "workflow_output" in result
        assert "summary" in result
    finally:
        os.unlink(path)
        os.environ.pop("CLAIMS_DB_PATH", None)


def test_parse_claim_type_exact():
    """Claim type parsing: exact matches."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("new") == "new"
    assert _parse_claim_type("duplicate") == "duplicate"
    assert _parse_claim_type("total_loss") == "total_loss"
    assert _parse_claim_type("total loss") == "total_loss"


def test_parse_claim_type_with_reasoning():
    """Claim type parsing: type on first line, reasoning on second."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("new\nReason: first-time submission.") == "new"
    assert _parse_claim_type("duplicate\nSame VIN and date as existing claim.") == "duplicate"
    assert _parse_claim_type("total_loss\nVehicle flooded.") == "total_loss"


def test_parse_claim_type_starts_with():
    """Claim type parsing: line starts with type."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("new claim submission") == "new"
    assert _parse_claim_type("Duplicate of CLM-EXIST01") == "duplicate"
    assert _parse_claim_type("total loss - flood damage") == "total_loss"


def test_parse_claim_type_default():
    """Claim type parsing: unknown output defaults to new."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("") == "new"
    assert _parse_claim_type("Unable to classify.") == "new"


def test_workflow_failure_sets_status_failed():
    """When workflow raises, claim status is set to 'failed' and audit log updated."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.database import get_connection, init_db
    from claim_agent.db.repository import ClaimRepository

    with open(Path(__file__).parent / "sample_claims" / "new_claim.json") as f:
        claim_data = json.load(f)

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        with patch("claim_agent.crews.main_crew.create_router_crew") as m:
            m.return_value.kickoff.side_effect = RuntimeError("simulated failure")
            with pytest.raises(RuntimeError, match="simulated failure"):
                run_claim_workflow(claim_data)
        repo = ClaimRepository(db_path=path)
        with get_connection(path) as conn:
            row = conn.execute("SELECT id FROM claims").fetchone()
        assert row is not None
        claim_id = row[0]
        claim = repo.get_claim(claim_id)
        assert claim["status"] == "failed"
        history = repo.get_claim_history(claim_id)
        assert any(h.get("new_status") == "failed" for h in history)
    finally:
        os.unlink(path)
        os.environ.pop("CLAIMS_DB_PATH", None)
