"""Focused tests for NICB/NISS anti-fraud compliance corpus content."""

import json
from pathlib import Path

import pytest


DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.mark.parametrize(
    "filename",
    [
        "california_auto_compliance.json",
        "texas_auto_compliance.json",
        "florida_auto_compliance.json",
        "new_york_auto_compliance.json",
        "georgia_auto_compliance.json",
    ],
)
def test_compliance_corpus_contains_nicb_and_niss_guidance(filename):
    """Each state compliance corpus should include NICB and NISS anti-fraud guidance."""
    compliance_file = DATA_DIR / filename
    assert compliance_file.exists(), f"Missing compliance corpus: {compliance_file}"

    data = json.loads(compliance_file.read_text())
    anti_fraud = data.get("anti_fraud_provisions", {})
    provisions = anti_fraud.get("provisions", [])

    combined_text = " ".join(
        f"{p.get('title', '')} {p.get('requirement', '')} {p.get('reference', '')}"
        for p in provisions
        if isinstance(p, dict)
    )

    assert "NICB" in combined_text, f"NICB guidance missing in {filename}"
    assert "NISS" in combined_text, f"NISS guidance missing in {filename}"
