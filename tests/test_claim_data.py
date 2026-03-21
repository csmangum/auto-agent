"""Unit tests for db/claim_data."""

from datetime import date

import pytest

from claim_agent.db.claim_data import claim_data_from_row
from claim_agent.models.claim import ClaimInput


class TestClaimDataFromRow:
    def test_builds_dict_with_all_keys(self):
        row = {
            "policy_number": "POL-001",
            "vin": "1HGBH41JXMN109186",
            "vehicle_year": 2021,
            "vehicle_make": "Honda",
            "vehicle_model": "Accord",
            "incident_date": "2025-01-15",
            "incident_description": "Rear-ended",
            "damage_description": "Bumper damage",
            "estimated_damage": 2500.0,
            "attachments": "[]",
            "claim_type": "new",
            "loss_state": "CA",
            "incident_latitude": 40.7128,
            "incident_longitude": -74.0060,
            "liability_percentage": None,
            "liability_basis": None,
        }
        result = claim_data_from_row(row)
        assert result["policy_number"] == "POL-001"
        assert result["vin"] == "1HGBH41JXMN109186"
        assert result["vehicle_year"] == 2021
        assert result["vehicle_make"] == "Honda"
        assert result["vehicle_model"] == "Accord"
        assert result["incident_date"] == "2025-01-15"
        assert result["incident_description"] == "Rear-ended"
        assert result["damage_description"] == "Bumper damage"
        assert result["estimated_damage"] == 2500.0
        assert result["attachments"] == []
        assert result["claim_type"] == "new"
        assert result["loss_state"] == "CA"
        assert result["incident_latitude"] == 40.7128
        assert result["incident_longitude"] == -74.0060
        assert result["liability_percentage"] is None
        assert result["liability_basis"] is None

    def test_uses_defaults_for_none(self):
        row = {}
        result = claim_data_from_row(row)
        assert result["policy_number"] == ""
        assert result["vin"] == ""
        assert result["vehicle_year"] == 0
        assert result["vehicle_make"] == ""
        assert result["attachments"] == []
        assert result["estimated_damage"] is None
        assert result["claim_type"] is None
        assert result["incident_latitude"] is None
        assert result["incident_longitude"] is None

    def test_parses_attachments_json_string(self):
        row = {"attachments": '["a.pdf", "b.jpg"]'}
        result = claim_data_from_row(row)
        assert result["attachments"] == ["a.pdf", "b.jpg"]

    def test_preserves_attachments_list(self):
        row = {"attachments": ["a.pdf"]}
        result = claim_data_from_row(row)
        assert result["attachments"] == ["a.pdf"]


class TestClaimInputIncidentCoordinates:
    def test_rejects_only_one_coordinate(self):
        with pytest.raises(ValueError, match="both"):
            ClaimInput(
                policy_number="POL-1",
                vin="1HGBH41JXMN109186",
                vehicle_year=2021,
                vehicle_make="Honda",
                vehicle_model="Accord",
                incident_date=date(2025, 1, 15),
                incident_description="x",
                damage_description="y",
                incident_latitude=40.0,
                incident_longitude=None,
            )
