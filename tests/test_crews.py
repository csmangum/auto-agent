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

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_parking.json") as f:
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


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_fraud_detection_crew_kickoff():
    """Run fraud detection crew on sample input (requires LLM)."""
    from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew

    with open(Path(__file__).parent / "sample_claims" / "fraud_claim.json") as f:
        claim_data = json.load(f)

    crew = create_fraud_detection_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = crew.kickoff(inputs=inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output
    assert "fraud" in str(output).lower() or "risk" in str(output).lower()


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_partial_loss_crew_kickoff():
    """Run partial loss crew on sample input (requires LLM)."""
    from claim_agent.crews.partial_loss_crew import create_partial_loss_crew

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_claim.json") as f:
        claim_data = json.load(f)

    crew = create_partial_loss_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = crew.kickoff(inputs=inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output


def test_run_claim_workflow_classification_only():
    """Test that run_claim_workflow returns expected keys and persists to DB."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.database import init_db

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_parking.json") as f:
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
        assert result["claim_type"] in ("new", "duplicate", "total_loss", "fraud", "partial_loss")
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
    assert _parse_claim_type("fraud") == "fraud"
    assert _parse_claim_type("partial_loss") == "partial_loss"
    assert _parse_claim_type("partial loss") == "partial_loss"


def test_parse_claim_type_with_reasoning():
    """Claim type parsing: type on first line, reasoning on second."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("new\nReason: first-time submission.") == "new"
    assert _parse_claim_type("duplicate\nSame VIN and date as existing claim.") == "duplicate"
    assert _parse_claim_type("total_loss\nVehicle flooded.") == "total_loss"
    assert _parse_claim_type("fraud\nMultiple fraud indicators detected.") == "fraud"
    assert _parse_claim_type("partial_loss\nRepairable bumper damage.") == "partial_loss"


def test_parse_claim_type_starts_with():
    """Claim type parsing: line starts with type."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("new claim submission") == "new"
    assert _parse_claim_type("Duplicate of CLM-EXIST01") == "duplicate"
    assert _parse_claim_type("total loss - flood damage") == "total_loss"
    assert _parse_claim_type("fraud - suspicious indicators") == "fraud"
    assert _parse_claim_type("partial loss - bumper repair") == "partial_loss"
    assert _parse_claim_type("partial_loss: fender damage repairable") == "partial_loss"


def test_parse_claim_type_default():
    """Claim type parsing: unknown output defaults to new."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("") == "new"
    assert _parse_claim_type("Unable to classify.") == "new"


def test_check_for_duplicates_empty_vin_returns_empty():
    """_check_for_duplicates returns [] when VIN is missing or blank."""
    from claim_agent.crews.main_crew import _check_for_duplicates

    assert _check_for_duplicates({}) == []
    assert _check_for_duplicates({"vin": ""}) == []
    assert _check_for_duplicates({"vin": "   "}) == []


def test_check_for_duplicates_vin_matching():
    """_check_for_duplicates returns repo matches for same VIN."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-A", "vin": "1HGBH41JXMN109186", "incident_date": "2024-01-15"},
        ],
    ):
        result = _check_for_duplicates({"vin": "1HGBH41JXMN109186"})
    assert len(result) == 1
    assert result[0]["id"] == "CLM-A"
    assert result[0]["vin"] == "1HGBH41JXMN109186"


def test_check_for_duplicates_filters_current_claim_id():
    """_check_for_duplicates excludes the claim with current_claim_id."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-A", "vin": "1HGBH41JXMN109186", "incident_date": "2024-01-15"},
            {"id": "CLM-B", "vin": "1HGBH41JXMN109186", "incident_date": "2024-01-20"},
        ],
    ):
        result = _check_for_duplicates(
            {"vin": "1HGBH41JXMN109186", "incident_date": "2024-01-15"},
            current_claim_id="CLM-A",
        )
    assert len(result) == 1
    assert result[0]["id"] == "CLM-B"


def test_check_for_duplicates_sorts_by_date_proximity():
    """_check_for_duplicates sets days_difference and sorts by proximity to incident_date."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-Far", "vin": "VIN123", "incident_date": "2024-03-01"},
            {"id": "CLM-Close", "vin": "VIN123", "incident_date": "2024-01-16"},
            {"id": "CLM-Exact", "vin": "VIN123", "incident_date": "2024-01-15"},
        ],
    ):
        result = _check_for_duplicates(
            {"vin": "VIN123", "incident_date": "2024-01-15"},
        )
    assert [r["id"] for r in result] == ["CLM-Exact", "CLM-Close", "CLM-Far"]
    assert result[0]["days_difference"] == 0
    assert result[1]["days_difference"] == 1
    assert result[2]["days_difference"] == 46


def test_check_for_duplicates_invalid_incident_date_on_claim_no_sort():
    """_check_for_duplicates does not sort when claim incident_date is invalid."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-A", "vin": "VIN123", "incident_date": "2024-01-15"},
            {"id": "CLM-B", "vin": "VIN123", "incident_date": "2024-01-20"},
        ],
    ):
        result = _check_for_duplicates(
            {"vin": "VIN123", "incident_date": "not-a-date"},
        )
    # Order unchanged (no days_difference); invalid target date skips proximity ranking
    assert len(result) == 2
    assert "days_difference" not in result[0]
    assert "days_difference" not in result[1]


def test_check_for_duplicates_invalid_incident_date_on_match_gets_999():
    """_check_for_duplicates assigns days_difference 999 when a match has bad incident_date."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-Bad", "vin": "VIN123", "incident_date": "bad"},
            {"id": "CLM-Good", "vin": "VIN123", "incident_date": "2024-01-15"},
        ],
    ):
        result = _check_for_duplicates(
            {"vin": "VIN123", "incident_date": "2024-01-15"},
        )
    assert result[0]["id"] == "CLM-Good"
    assert result[0]["days_difference"] == 0
    assert result[1]["id"] == "CLM-Bad"
    assert result[1]["days_difference"] == 999


def test_workflow_failure_sets_status_failed():
    """When workflow raises, claim status is set to 'failed' and audit log updated."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.database import get_connection, init_db
    from claim_agent.db.repository import ClaimRepository

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_parking.json") as f:
        claim_data = json.load(f)

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        with patch("claim_agent.crews.main_crew.get_llm") as mock_llm:
            mock_llm.return_value = None
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
