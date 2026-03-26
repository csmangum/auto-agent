"""Tests for claim_agent.tools.fraud_utils helpers."""

from datetime import date, datetime
from unittest.mock import MagicMock

from claim_agent.tools import fraud_utils


def test_as_trimmed_str_non_string_returns_empty():
    assert fraud_utils.as_trimmed_str(None) == ""
    assert fraud_utils.as_trimmed_str(42) == ""


def test_coerce_date_variants():
    dt = datetime(2024, 3, 15, 10, 30, 0)
    assert fraud_utils.coerce_date(dt) is dt
    d = date(2024, 3, 15)
    out = fraud_utils.coerce_date(d)
    assert out == datetime(2024, 3, 15, 0, 0, 0)
    assert fraud_utils.coerce_date("  2024-03-15  ") == datetime(2024, 3, 15, 0, 0, 0)
    assert fraud_utils.coerce_date("not-a-date") is None
    assert fraud_utils.coerce_date(12345) is None


def test_extract_provider_names_from_strings_and_lists():
    repo = MagicMock()
    repo.get_claim_parties.return_value = []
    claim = {
        "claim_id": "CLM-1",
        "provider_name": " Dr. A ",
        "provider_names": ["  Shop B  ", {"name": "Nested C", "other": 1}],
        "medical_providers": [{"provider_name": "  D  "}],
        "repair_shops": [{"shop_name": "E"}, {"no_name": True}],
    }
    names = fraud_utils.extract_provider_names(claim, repo)
    assert names == ["D", "Dr. A", "E", "Nested C", "Shop B"]
    repo.get_claim_parties.assert_called_once_with("CLM-1", party_type="provider")


def test_extract_provider_names_repo_failure_is_ignored(caplog):
    repo = MagicMock()
    repo.get_claim_parties.side_effect = RuntimeError("db down")
    claim = {"claim_id": "CLM-2", "doctor_name": "Dr. Z"}
    with caplog.at_level("DEBUG"):
        names = fraud_utils.extract_provider_names(claim, repo)
    assert names == ["Dr. Z"]
    assert "Unable to load provider parties" in caplog.text
