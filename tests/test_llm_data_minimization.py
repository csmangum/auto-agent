"""Tests for LLM data minimization."""

from unittest.mock import MagicMock, patch

from claim_agent.utils.llm_data_minimization import minimize_claim_data_for_crew
from claim_agent.utils.pii_masking import mask_policy_number, mask_vin


class TestMinimizeClaimDataForCrew:
    """Tests for minimize_claim_data_for_crew."""

    def test_filters_to_allowlist(self):
        """Only allowlisted fields are included."""
        claim = {
            "claim_id": "CLM-1",
            "policy_number": "POL-12345",
            "vin": "1HGCM82633A123456",
            "vehicle_year": 2020,
            "incident_description": "Parking lot fender bender",
            "secret_field": "should be excluded",
        }
        result = minimize_claim_data_for_crew(claim, "partial_loss", mask_pii=False)
        assert "claim_id" in result
        assert "policy_number" in result
        assert "vin" in result
        assert "vehicle_year" in result
        assert "incident_description" in result
        assert "secret_field" not in result

    def test_masks_pii_when_enabled(self):
        """policy_number and vin are masked when mask_pii=True."""
        claim = {
            "claim_id": "CLM-1",
            "policy_number": "POL-12345-001",
            "vin": "1HGCM82633A123456",
            "incident_description": "Test",
        }
        result = minimize_claim_data_for_crew(claim, "partial_loss", mask_pii=True)
        assert result["policy_number"] == mask_policy_number("POL-12345-001")
        assert result["vin"] == mask_vin("1HGCM82633A123456")

    def test_minimizes_attachments(self):
        """Attachment descriptions are stripped; url and type kept."""
        claim = {
            "claim_id": "CLM-1",
            "attachments": [
                {
                    "url": "https://example.com/photo.jpg",
                    "type": "photo",
                    "description": "Front damage",
                },
            ],
        }
        result = minimize_claim_data_for_crew(claim, "partial_loss", mask_pii=False)
        assert result["attachments"] == [{"url": "https://example.com/photo.jpg", "type": "photo"}]

    def test_strips_party_pii_for_bodily_injury(self):
        """For bodily_injury, party name/email/phone/address are stripped."""
        claim = {
            "claim_id": "CLM-1",
            "parties": [
                {
                    "party_type": "claimant",
                    "name": "John Doe",
                    "email": "john@example.com",
                    "phone": "555-1234",
                    "role": "driver",
                },
            ],
        }
        result = minimize_claim_data_for_crew(claim, "bodily_injury", mask_pii=False)
        assert result["parties"] == [{"party_type": "claimant", "role": "driver"}]

    def test_unknown_crew_allows_all(self):
        """Unknown crew name allows all fields through when mask_pii=False."""
        claim = {"claim_id": "CLM-1", "custom_field": "value"}
        result = minimize_claim_data_for_crew(claim, "unknown_crew", mask_pii=False)
        assert result == claim

    def test_unknown_crew_masks_pii_when_enabled(self):
        """Unknown crew still masks policy_number and vin when mask_pii=True (default-deny for PII)."""
        claim = {
            "claim_id": "CLM-1",
            "policy_number": "POL-12345",
            "vin": "1HGCM82633A123456",
            "custom_field": "value",
        }
        result = minimize_claim_data_for_crew(claim, "unknown_crew", mask_pii=True)
        assert result["policy_number"] == mask_policy_number("POL-12345")
        assert result["vin"] == mask_vin("1HGCM82633A123456")

    def test_force_allowlist_applies_when_global_minimization_disabled(self):
        """With PRIVACY_LLM_DATA_MINIMIZATION=false, force_allowlist still filters to allowlist."""
        claim = {
            "claim_id": "CLM-1",
            "incident_description": "Rear-end",
            "secret_field": "must_not_appear",
        }
        mock_settings = MagicMock()
        mock_settings.privacy.llm_data_minimization = False
        with patch(
            "claim_agent.utils.llm_data_minimization.get_settings", return_value=mock_settings
        ):
            bypass = minimize_claim_data_for_crew(claim, "router", force_allowlist=False)
            forced = minimize_claim_data_for_crew(claim, "router", force_allowlist=True)
        assert "secret_field" in bypass
        assert "secret_field" not in forced
        assert forced.get("claim_id") == "CLM-1"
        assert forced.get("incident_description") == "Rear-end"
