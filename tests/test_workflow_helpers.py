"""Unit tests for workflow helper functions."""

from unittest.mock import patch


# Import via main_crew to avoid circular import (workflow -> orchestrator -> stages -> crews -> main_crew -> workflow).
# Helpers live in claim_agent.workflow.claim_analysis and claim_agent.workflow.duplicate_detection.
from claim_agent.crews.main_crew import (
    _check_economic_total_loss,
    _damage_tags_overlap,
    _extract_damage_tags,
    _filter_weak_fraud_indicators,
)
from claim_agent.workflow.escalation import _sla_hours_for_priority


class TestExtractDamageTags:
    """Tests for _extract_damage_tags."""

    def test_empty_text_returns_empty_set(self):
        assert _extract_damage_tags("") == set()
        assert _extract_damage_tags(None) == set()

    def test_extracts_front_tags(self):
        assert "front" in _extract_damage_tags("front bumper damaged")
        assert "front" in _extract_damage_tags("hood dented, grille cracked")

    def test_extracts_rear_tags(self):
        assert "rear" in _extract_damage_tags("rear bumper and trunk damaged")

    def test_extracts_side_tags(self):
        assert "side" in _extract_damage_tags("door and fender damaged")
        assert "side" in _extract_damage_tags("mirror broken")

    def test_extracts_glass_tags(self):
        assert "glass" in _extract_damage_tags("windshield cracked")
        assert "glass" in _extract_damage_tags("window shattered")

    def test_extracts_catastrophic_tags(self):
        # "flood" matches (word boundary); "flooded" does not match \bflood\b
        assert "catastrophic" in _extract_damage_tags("vehicle flood damage")
        assert "catastrophic" in _extract_damage_tags("fire destroyed the car")

    def test_extracts_multiple_tags(self):
        tags = _extract_damage_tags("front bumper, door, and windshield damaged")
        assert "front" in tags
        assert "side" in tags
        assert "glass" in tags

    def test_word_boundary_avoids_false_positives(self):
        # "accident" should not match "dent"
        assert "side" not in _extract_damage_tags("accident")
        # "misfired" should not match "fire"
        assert "catastrophic" not in _extract_damage_tags("engine misfired")


class TestDamageTagsOverlap:
    """Tests for _damage_tags_overlap."""

    def test_empty_sets_return_false(self):
        assert _damage_tags_overlap(set(), {"front"}) is False
        assert _damage_tags_overlap({"front"}, set()) is False
        assert _damage_tags_overlap(set(), set()) is False

    def test_overlapping_sets_return_true(self):
        assert _damage_tags_overlap({"front", "side"}, {"side", "rear"}) is True
        assert _damage_tags_overlap({"glass"}, {"glass"}) is True

    def test_disjoint_sets_return_false(self):
        assert _damage_tags_overlap({"front"}, {"rear"}) is False
        assert _damage_tags_overlap({"side"}, {"engine"}) is False


class TestFilterWeakFraudIndicators:
    """Tests for _filter_weak_fraud_indicators."""

    def test_removes_weak_indicators(self):
        indicators = [
            "damage_near_or_above_vehicle_value",
            "suspicious_timing",
            "incident_damage_description_mismatch",
        ]
        result = _filter_weak_fraud_indicators(indicators)
        assert result == ["suspicious_timing"]

    def test_preserves_strong_indicators(self):
        indicators = ["multiple_claims_same_vin", "staged_accident"]
        assert _filter_weak_fraud_indicators(indicators) == indicators

    def test_empty_list_returns_empty(self):
        assert _filter_weak_fraud_indicators([]) == []


class TestSlaHoursForPriority:
    """Tests for _sla_hours_for_priority."""

    def test_default_priorities(self):
        # With default env (no overrides), verify expected values
        assert _sla_hours_for_priority("critical") == 24
        assert _sla_hours_for_priority("high") == 24
        assert _sla_hours_for_priority("medium") == 48
        assert _sla_hours_for_priority("low") == 72

    def test_unknown_priority_falls_back_to_low(self):
        # Unknown priority uses ESCALATION_SLA_HOURS_LOW and logs warning
        result = _sla_hours_for_priority("unknown")
        assert result == 72

    def test_typo_priority_falls_back_to_low(self):
        # Typos like "medum" use ESCALATION_SLA_HOURS_LOW
        result = _sla_hours_for_priority("medum")
        assert result == 72


class TestCheckEconomicTotalLoss:
    """Tests for _check_economic_total_loss."""

    def test_no_estimated_damage_returns_base_context(self):
        result = _check_economic_total_loss({
            "damage_description": "door dented",
            "incident_description": "parking lot bump",
        })
        assert result["is_economic_total_loss"] is False
        assert "is_catastrophic_event" in result
        assert "damage_indicates_total_loss" in result
        assert "damage_is_repairable" in result

    def test_catastrophic_keywords_set_flags(self):
        result = _check_economic_total_loss({
            "damage_description": "vehicle flooded and submerged",
            "incident_description": "heavy rain",
        })
        assert result["is_catastrophic_event"] is True
        assert result["damage_indicates_total_loss"] is True

    def test_repairable_damage_without_total_loss_keywords(self):
        result = _check_economic_total_loss({
            "damage_description": "bumper and fender damaged",
            "incident_description": "rear-ended",
        })
        assert result["damage_is_repairable"] is True
        assert result["damage_indicates_total_loss"] is False

    def test_economic_total_loss_with_high_ratio(self):
        with patch("claim_agent.tools.valuation_logic.fetch_vehicle_value_impl") as mock_fetch:
            mock_fetch.return_value = '{"value": 10000}'
            result = _check_economic_total_loss({
                "vin": "1HGBH41JXMN109186",
                "vehicle_year": 2020,
                "vehicle_make": "Honda",
                "vehicle_model": "Accord",
                "damage_description": "totaled, frame bent",
                "incident_description": "rollover",
                "estimated_damage": 12000,
            })
        assert result["is_economic_total_loss"] is True
        assert result["vehicle_value"] == 10000
        assert result["damage_to_value_ratio"] == 1.2
