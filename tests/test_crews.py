"""Integration tests for crews (require LLM; can be skipped if no API key)."""

import json
import os
import sys
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

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
    """Test that run_claim_workflow returns expected keys (mock: we only check structure if no key)."""
    from claim_agent.crews.main_crew import run_claim_workflow

    with open(Path(__file__).parent / "sample_claims" / "new_claim.json") as f:
        claim_data = json.load(f)

    if SKIP_CREW:
        pytest.skip("OPENAI_API_KEY not set")
    result = run_claim_workflow(claim_data)
    assert "claim_type" in result
    assert result["claim_type"] in ("new", "duplicate", "total_loss")
    assert "workflow_output" in result
    assert "summary" in result
