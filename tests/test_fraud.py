"""Tests for fraud detection workflow."""

import json
import logging
from datetime import date
from unittest.mock import patch

from claim_agent.config.settings import get_fraud_config
from claim_agent.db.audit_events import AUDIT_EVENT_SIU_CASE_CREATED
from claim_agent.db.repository import ClaimRepository
from claim_agent.models.claim import ClaimInput
from claim_agent.tools.fraud_detectors import KNOWN_FRAUD_PATTERNS
from claim_agent.tools.fraud_logic import (
    analyze_claim_patterns_impl,
    cross_reference_fraud_indicators_impl,
    perform_fraud_assessment_impl,
)
from tests.conftest import LogCaptureHandler


class TestFraudPatternAnalysis:
    """Tests for analyze_claim_patterns_impl."""

    def test_empty_claim_data(self):
        """Empty claim data returns empty pattern result."""
        result = json.loads(analyze_claim_patterns_impl({}))
        assert result["patterns_detected"] == []
        assert result["pattern_score"] == 0

    def test_staged_accident_keywords_detected(self):
        """Staged accident keywords are detected in descriptions."""
        claim_data = {
            "vin": "TEST123",
            "incident_date": "2026-01-15",
            "incident_description": "Multiple occupants were all injured. Witnesses left the scene.",
            "damage_description": "Front bumper damage",
        }
        result = json.loads(analyze_claim_patterns_impl(claim_data))
        assert "staged_accident_indicators" in result["patterns_detected"]
        assert result["pattern_score"] > 0

    def test_timing_red_flags_detected(self):
        """Timing red flags like 'new policy' are detected."""
        claim_data = {
            "vin": "TEST456",
            "incident_date": "2026-01-15",
            "incident_description": "Accident occurred on new policy, just purchased yesterday.",
            "damage_description": "Side damage",
        }
        result = json.loads(analyze_claim_patterns_impl(claim_data))
        assert "new_policy_timing" in result["patterns_detected"]
        assert len(result["timing_flags"]) > 0


class TestFraudCrossReference:
    """Tests for cross_reference_fraud_indicators_impl."""

    def test_empty_claim_data(self):
        """Empty claim data returns empty cross-reference result."""
        result = json.loads(cross_reference_fraud_indicators_impl({}))
        assert result["fraud_keywords_found"] == []
        assert result["risk_level"] == "low"
        assert result["cross_reference_score"] == 0

    def test_fraud_keywords_detected(self):
        """Fraud keywords in descriptions are detected."""
        claim_data = {
            "incident_description": "Staged accident with inflated damage claims",
            "damage_description": "Pre-existing damage and exaggerated repairs needed",
        }
        result = json.loads(cross_reference_fraud_indicators_impl(claim_data))
        assert len(result["fraud_keywords_found"]) > 0
        assert "staged" in result["fraud_keywords_found"] or "inflated" in result["fraud_keywords_found"]
        assert result["cross_reference_score"] > 0

    def test_damage_exceeds_value_detected(self):
        """Damage estimate exceeding vehicle value is flagged."""
        claim_data = {
            "vin": "1HGBH41JXMN109186",  # Known VIN with value 12000
            "vehicle_year": 2020,
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
            "incident_description": "Minor fender bender",
            "damage_description": "Complete front end damage",
            "estimated_damage": 15000,  # Higher than vehicle value
        }
        result = json.loads(cross_reference_fraud_indicators_impl(claim_data))
        # Should detect damage near/exceeds vehicle value
        has_damage_flag = any(
            "damage" in match for match in result["database_matches"]
        )
        assert has_damage_flag or result["cross_reference_score"] > 0


class TestFraudAssessment:
    """Tests for perform_fraud_assessment_impl."""

    def test_empty_claim_data(self):
        """Empty claim data returns manual review recommendation."""
        result = json.loads(perform_fraud_assessment_impl({}))
        assert "Invalid claim data" in result["recommended_action"]

    def test_low_risk_claim(self):
        """Clean claim with no indicators results in low risk."""
        claim_data = {
            "vin": "CLEAN123",
            "incident_date": "2026-01-15",
            "incident_description": "Minor parking lot fender bender.",
            "damage_description": "Small dent on rear bumper.",
            "estimated_damage": 500,
        }
        result = json.loads(perform_fraud_assessment_impl(claim_data))
        assert result["fraud_likelihood"] == "low"
        assert result["should_block"] is False
        assert result["siu_referral"] is False

    def test_high_risk_claim(self, temp_db):
        """Claim with multiple fraud indicators results in high risk."""
        repo = ClaimRepository()
        claim_id = repo.create_claim(
            ClaimInput(
                policy_number="POL-FRAUD",
                vin="FRAUD123",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date=date(2026, 1, 15),
                incident_description="Staged accident.",
                damage_description="Inflated damage.",
                estimated_damage=50000,
            )
        )
        claim_data = {
            "claim_id": claim_id,
            "vin": "FRAUD123",
            "incident_date": "2026-01-15",
            "incident_description": "Staged accident with multiple occupants. Witnesses left scene. Brake checked.",
            "damage_description": "Inflated damage. Pre-existing dents. Complete destruction.",
            "estimated_damage": 50000,
        }
        result = json.loads(perform_fraud_assessment_impl(claim_data))
        assert result["fraud_likelihood"] in ("high", "critical")
        assert len(result["fraud_indicators"]) >= 2
        assert result["siu_referral"] is True
        assert "siu_case_id" in result
        assert result["siu_case_id"] is not None
        assert result["siu_case_id"].startswith("SIU-MOCK-")
        assert result["siu_case_id_persisted"] is True

    def test_critical_risk_triggers_block(self, temp_db):
        """Critical risk claims should be blocked; input is designed to exceed critical_risk_threshold and critical_indicator_count."""
        repo = ClaimRepository()
        claim_id = repo.create_claim(
            ClaimInput(
                policy_number="POL-BLOCK",
                vin="BLOCK123",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date=date(2026, 1, 15),
                incident_description="Staged accident.",
                damage_description="Inflated damage.",
                estimated_damage=100000,
            )
        )
        claim_data = {
            "claim_id": claim_id,
            "vin": "BLOCK123",
            "incident_date": "2026-01-15",
            "incident_description": (
                "Staged accident. Multiple occupants all injured. "
                "Witnesses left. No witnesses. Brake checked. Sudden stop."
            ),
            "damage_description": (
                "Inflated pre-existing fabricated misrepresentation "
                "exaggerated total destruction beyond repair catastrophic"
            ),
            "estimated_damage": 100000,
        }
        result = json.loads(perform_fraud_assessment_impl(claim_data))
        assert result["fraud_likelihood"] == "critical"
        assert result["should_block"] is True
        assert result["siu_referral"] is True
        assert "siu_case_id" in result
        assert result["siu_case_id"] is not None
        assert result["siu_case_id"].startswith("SIU-MOCK-")
        assert result["siu_case_id_persisted"] is True

    def test_siu_referral_with_stub_adapter_sets_case_id_none(self, monkeypatch):
        """When SIU adapter is stub, siu_case_id is None (NotImplementedError caught)."""
        from claim_agent.adapters.registry import reset_adapters

        reset_adapters()
        monkeypatch.setenv("SIU_ADAPTER", "stub")
        claim_data = {
            "vin": "FRAUD123",
            "incident_date": "2026-01-15",
            "incident_description": "Staged accident. Brake checked.",
            "damage_description": "Inflated damage. Complete destruction.",
            "estimated_damage": 50000,
        }
        result = json.loads(perform_fraud_assessment_impl(claim_data))
        assert result["siu_referral"] is True
        assert result["siu_case_id"] is None

    def test_siu_referral_persists_case_id_and_audit(self, temp_db):
        """When siu_referral=true and claim exists, siu_case_id is stored and audit entry written."""
        repo = ClaimRepository()
        claim_input = ClaimInput(
            policy_number="POL-SIU-TEST",
            vin="FRAUD123",
            vehicle_year=2020,
            vehicle_make="Honda",
            vehicle_model="Civic",
            incident_date=date(2026, 1, 15),
            incident_description="Staged accident with multiple occupants. Witnesses left scene.",
            damage_description="Inflated damage. Pre-existing dents. Complete destruction.",
            estimated_damage=50000,
        )
        claim_id = repo.create_claim(claim_input)

        claim_data = {
            "claim_id": claim_id,
            "vin": "FRAUD123",
            "incident_date": "2026-01-15",
            "incident_description": "Staged accident with multiple occupants. Witnesses left scene.",
            "damage_description": "Inflated damage. Pre-existing dents. Complete destruction.",
            "estimated_damage": 50000,
        }
        result = json.loads(perform_fraud_assessment_impl(claim_data))

        assert result["siu_referral"] is True
        assert result["siu_case_id"] is not None
        assert result["siu_case_id"].startswith("SIU-MOCK-")
        assert result["siu_case_id_persisted"] is True

        claim = repo.get_claim(claim_id)
        assert claim is not None
        assert claim["siu_case_id"] == result["siu_case_id"]

        history, _ = repo.get_claim_history(claim_id)
        siu_entries = [h for h in history if h["action"] == AUDIT_EVENT_SIU_CASE_CREATED]
        assert len(siu_entries) == 1
        assert f"SIU case created: {result['siu_case_id']}" in siu_entries[0]["details"]

    def test_siu_referral_persistence_failure_returns_case_id_and_persisted_false(
        self, temp_db
    ):
        """When update_claim_siu_case_id raises, response has siu_case_id and siu_case_id_persisted=False."""
        repo = ClaimRepository()
        claim_id = repo.create_claim(
            ClaimInput(
                policy_number="POL-PERSIST-FAIL",
                vin="FRAUD123",
                vehicle_year=2020,
                vehicle_make="Honda",
                vehicle_model="Civic",
                incident_date=date(2026, 1, 15),
                incident_description="Staged accident with multiple occupants.",
                damage_description="Inflated damage. Pre-existing dents.",
                estimated_damage=50000,
            )
        )
        claim_data = {
            "claim_id": claim_id,
            "vin": "FRAUD123",
            "incident_date": "2026-01-15",
            "incident_description": "Staged accident with multiple occupants.",
            "damage_description": "Inflated damage. Pre-existing dents.",
            "estimated_damage": 50000,
        }

        logic_logger = logging.getLogger("claim_agent.tools.fraud_logic")
        cap = LogCaptureHandler()
        logic_logger.addHandler(cap)
        logic_logger.setLevel(logging.WARNING)
        try:
            with patch(
                "claim_agent.tools.fraud_logic.ClaimRepository"
            ) as mock_repo_cls:
                mock_instance = mock_repo_cls.return_value
                mock_instance.update_claim_siu_case_id.side_effect = RuntimeError(
                    "DB connection failed"
                )
                result = json.loads(perform_fraud_assessment_impl(claim_data))
        finally:
            logic_logger.removeHandler(cap)

        assert result["siu_referral"] is True
        assert result["siu_case_id"] is not None
        assert result["siu_case_id"].startswith("SIU-MOCK-")
        assert result["siu_case_id_persisted"] is False
        assert any("Failed to persist siu_case_id" in m for m in cap.messages)


class TestFraudConfig:
    """Tests for fraud configuration values."""

    def test_fraud_config_exists(self):
        """Fraud configuration has expected keys."""
        expected_keys = [
            "multiple_claims_days",
            "multiple_claims_threshold",
            "fraud_keyword_score",
            "multiple_claims_score",
            "timing_anomaly_score",
            "damage_mismatch_score",
            "high_risk_threshold",
            "medium_risk_threshold",
            "critical_risk_threshold",
            "critical_indicator_count",
        ]
        for key in expected_keys:
            assert key in get_fraud_config()

    def test_known_fraud_patterns_exist(self):
        """Known fraud patterns database has expected categories."""
        expected_categories = [
            "staged_accident_keywords",
            "suspicious_claim_keywords",
            "timing_red_flags",
            "damage_fraud_keywords",
        ]
        for category in expected_categories:
            assert category in KNOWN_FRAUD_PATTERNS
            assert len(KNOWN_FRAUD_PATTERNS[category]) > 0


class TestIntegration:
    """Integration tests for the fraud detection workflow."""

    def test_full_fraud_assessment_pipeline(self):
        """Test complete fraud assessment pipeline."""
        claim_data = {
            "claim_id": "TEST-FRAUD-001",
            "vin": "JM1BL1S58A1234568",
            "incident_date": "2026-01-25",
            "incident_description": "Staged collision. Multiple occupants injured.",
            "damage_description": "Inflated damage estimate. Pre-existing dents visible.",
            "estimated_damage": 25000,
            "vehicle_year": 2020,
            "vehicle_make": "Mazda",
            "vehicle_model": "3",
        }

        # Step 1: Pattern analysis
        pattern_result = json.loads(analyze_claim_patterns_impl(claim_data))
        assert "pattern_score" in pattern_result

        # Step 2: Cross-reference
        xref_result = json.loads(cross_reference_fraud_indicators_impl(claim_data))
        assert "cross_reference_score" in xref_result

        # Step 3: Full assessment
        assessment = json.loads(perform_fraud_assessment_impl(
            claim_data, pattern_result, xref_result
        ))

        # Verify assessment structure
        assert "fraud_score" in assessment
        assert "fraud_likelihood" in assessment
        assert "fraud_indicators" in assessment
        assert "recommended_action" in assessment
        assert "should_block" in assessment
        assert "siu_referral" in assessment

        # This claim should have elevated risk
        assert assessment["fraud_score"] > 0
        assert len(assessment["fraud_indicators"]) > 0
