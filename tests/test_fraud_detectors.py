"""Unit tests for pluggable fraud detectors."""


from claim_agent.tools.fraud_detectors import (
    KNOWN_FRAUD_PATTERNS,
    register_fraud_detector,
    run_fraud_detectors,
)


class TestRunFraudDetectors:
    """Tests for run_fraud_detectors."""

    def test_empty_claim_data_returns_empty(self):
        """Empty or invalid claim data returns no indicators."""
        assert run_fraud_detectors({}) == []
        assert run_fraud_detectors(None) == []  # type: ignore[arg-type]

    def test_staged_keyword_detected(self):
        """Staged accident keywords in descriptions are detected."""
        claim_data = {
            "incident_description": "Staged accident with multiple occupants.",
            "damage_description": "Bumper damage.",
        }
        result = run_fraud_detectors(claim_data)
        assert "staged" in result
        assert "multiple_occupants" in result

    def test_suspicious_keyword_detected(self):
        """Suspicious claim keywords are detected."""
        claim_data = {
            "incident_description": "Inflated damage claim.",
            "damage_description": "Pre-existing damage exaggerated.",
        }
        result = run_fraud_detectors(claim_data)
        assert "inflated" in result
        assert "pre-existing" in result
        assert "exaggerated" in result

    def test_timing_red_flags_detected(self):
        """Timing red flags like 'new policy' are detected."""
        claim_data = {
            "incident_description": "Accident on new policy, just purchased.",
            "damage_description": "Minor scratch.",
        }
        result = run_fraud_detectors(claim_data)
        assert "new_policy" in result
        assert "just_purchased" in result

    def test_damage_fraud_keywords_detected(self):
        """Damage fraud keywords are detected."""
        claim_data = {
            "incident_description": "Collision.",
            "damage_description": "Total destruction, complete loss, beyond repair.",
        }
        result = run_fraud_detectors(claim_data)
        assert "total_destruction" in result
        assert "complete_loss" in result
        assert "beyond_repair" in result

    def test_indicators_deduplicated_and_sorted(self):
        """Multiple detectors returning same indicator deduplicate; result is sorted."""
        claim_data = {
            "incident_description": "staged staged inflated",
            "damage_description": "staged",
        }
        result = run_fraud_detectors(claim_data)
        assert result == sorted(set(result))
        assert result.count("staged") == 1


class TestRegisterFraudDetector:
    """Tests for register_fraud_detector decorator."""

    def test_custom_detector_invoked(self):
        """A custom detector registered via register_fraud_detector is invoked."""
        marker = "__test_custom_detector_marker"

        @register_fraud_detector
        def _test_detector(claim_data: dict, ctx=None):
            if claim_data.get(marker):
                return ["custom_detector_ok"]
            return []

        try:
            result = run_fraud_detectors({marker: True})
            assert "custom_detector_ok" in result
        finally:
            # Remove our detector to avoid affecting other tests
            from claim_agent.tools import fraud_detectors

            fraud_detectors._FRAUD_DETECTORS.remove(_test_detector)

    def test_decorator_returns_function(self):
        """register_fraud_detector used as decorator returns the original function."""
        def _dummy_detector(claim_data: dict, ctx=None):
            return []

        wrapped = register_fraud_detector(_dummy_detector)
        assert wrapped is _dummy_detector

        # Clean up
        from claim_agent.tools import fraud_detectors

        fraud_detectors._FRAUD_DETECTORS.remove(_dummy_detector)


class TestKnownFraudPatterns:
    """Tests for KNOWN_FRAUD_PATTERNS structure."""

    def test_all_categories_have_keywords(self):
        """All KNOWN_FRAUD_PATTERNS categories are non-empty lists."""
        for category, keywords in KNOWN_FRAUD_PATTERNS.items():
            assert isinstance(keywords, list), f"{category} should be a list"
            assert len(keywords) > 0, f"{category} should not be empty"

    def test_keyword_detector_uses_all_categories(self):
        """Keyword detector covers all pattern categories (timing, damage, etc.)."""
        # timing_red_flags
        r = run_fraud_detectors({"incident_description": "first day of policy"})
        assert any("first_day" in i or "policy" in i for i in r)

        # damage_fraud_keywords
        r = run_fraud_detectors({"damage_description": "catastrophic damage"})
        assert "catastrophic" in r
