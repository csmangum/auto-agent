"""Unit tests for data_loader module."""

import json
import os
import tempfile


class TestDataLoader:
    """Tests for data_loader.py."""

    def test_load_mock_db_default_path(self):
        """Test load_mock_db uses default path when env not set."""
        from claim_agent.tools.data_loader import load_mock_db

        # Temporarily remove MOCK_DB_PATH if set
        original = os.environ.get("MOCK_DB_PATH")
        try:
            if "MOCK_DB_PATH" in os.environ:
                del os.environ["MOCK_DB_PATH"]
            
            db = load_mock_db()
            # Should return default structure if file doesn't exist at default path
            # or the actual data if it does
            assert isinstance(db, dict)
            assert "policies" in db or db == {"policies": {}, "claims": [], "vehicle_values": {}}
        finally:
            if original is not None:
                os.environ["MOCK_DB_PATH"] = original

    def test_load_mock_db_custom_path(self):
        """Test load_mock_db uses custom path from env."""
        from claim_agent.tools.data_loader import load_mock_db

        # Create a temp file with custom data
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"policies": {"TEST-001": {"deductible": 1000}}, "claims": [], "vehicle_values": {}}, f)
            path = f.name

        original = os.environ.get("MOCK_DB_PATH")
        try:
            os.environ["MOCK_DB_PATH"] = path
            db = load_mock_db()
            assert "TEST-001" in db["policies"]
            assert db["policies"]["TEST-001"]["deductible"] == 1000
        finally:
            if original is not None:
                os.environ["MOCK_DB_PATH"] = original
            elif "MOCK_DB_PATH" in os.environ:
                del os.environ["MOCK_DB_PATH"]
            os.unlink(path)

    def test_load_mock_db_invalid_json(self):
        """Test load_mock_db handles invalid JSON gracefully."""
        from claim_agent.tools.data_loader import load_mock_db

        # Create a temp file with invalid JSON
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {")
            path = f.name

        original = os.environ.get("MOCK_DB_PATH")
        try:
            os.environ["MOCK_DB_PATH"] = path
            db = load_mock_db()
            # Should return default structure on JSON error
            assert db == {"policies": {}, "claims": [], "vehicle_values": {}}
        finally:
            if original is not None:
                os.environ["MOCK_DB_PATH"] = original
            elif "MOCK_DB_PATH" in os.environ:
                del os.environ["MOCK_DB_PATH"]
            os.unlink(path)

    def test_load_mock_db_missing_file(self):
        """Test load_mock_db handles missing file gracefully."""
        from claim_agent.tools.data_loader import load_mock_db

        original = os.environ.get("MOCK_DB_PATH")
        try:
            os.environ["MOCK_DB_PATH"] = "/nonexistent/path/mock_db.json"
            db = load_mock_db()
            # Should return default structure when file missing
            assert db == {"policies": {}, "claims": [], "vehicle_values": {}}
        finally:
            if original is not None:
                os.environ["MOCK_DB_PATH"] = original
            elif "MOCK_DB_PATH" in os.environ:
                del os.environ["MOCK_DB_PATH"]

    def test_load_california_compliance_default_path(self):
        """Test load_california_compliance uses default path."""
        from claim_agent.tools.data_loader import load_california_compliance

        original = os.environ.get("CA_COMPLIANCE_PATH")
        try:
            if "CA_COMPLIANCE_PATH" in os.environ:
                del os.environ["CA_COMPLIANCE_PATH"]
            
            data = load_california_compliance()
            # May be None if file doesn't exist or valid dict if it does
            assert data is None or isinstance(data, dict)
        finally:
            if original is not None:
                os.environ["CA_COMPLIANCE_PATH"] = original

    def test_load_california_compliance_custom_path(self):
        """Test load_california_compliance uses custom path."""
        from claim_agent.tools.data_loader import load_california_compliance

        # Create temp file with compliance data
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"test_section": {"provision": "test"}}, f)
            path = f.name

        original = os.environ.get("CA_COMPLIANCE_PATH")
        try:
            os.environ["CA_COMPLIANCE_PATH"] = path
            data = load_california_compliance()
            assert data is not None
            assert "test_section" in data
        finally:
            if original is not None:
                os.environ["CA_COMPLIANCE_PATH"] = original
            elif "CA_COMPLIANCE_PATH" in os.environ:
                del os.environ["CA_COMPLIANCE_PATH"]
            os.unlink(path)

    def test_load_california_compliance_missing_file(self):
        """Test load_california_compliance returns None for missing file."""
        from claim_agent.tools.data_loader import load_california_compliance

        original = os.environ.get("CA_COMPLIANCE_PATH")
        try:
            os.environ["CA_COMPLIANCE_PATH"] = "/nonexistent/path.json"
            data = load_california_compliance()
            assert data is None
        finally:
            if original is not None:
                os.environ["CA_COMPLIANCE_PATH"] = original
            elif "CA_COMPLIANCE_PATH" in os.environ:
                del os.environ["CA_COMPLIANCE_PATH"]

    def test_load_california_compliance_invalid_json(self):
        """Test load_california_compliance returns None for invalid JSON."""
        from claim_agent.tools.data_loader import load_california_compliance

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("invalid json {{{")
            path = f.name

        original = os.environ.get("CA_COMPLIANCE_PATH")
        try:
            os.environ["CA_COMPLIANCE_PATH"] = path
            data = load_california_compliance()
            assert data is None
        finally:
            if original is not None:
                os.environ["CA_COMPLIANCE_PATH"] = original
            elif "CA_COMPLIANCE_PATH" in os.environ:
                del os.environ["CA_COMPLIANCE_PATH"]
            os.unlink(path)


class TestLogicEdgeCases:
    """Additional tests for logic.py edge cases."""

    def test_compute_similarity_identical(self):
        """Test compute_similarity with identical strings."""
        from claim_agent.tools.logic import compute_similarity_impl

        result = json.loads(compute_similarity_impl("test", "test"))
        assert result["similarity_score"] == 100.0
        assert result["is_duplicate"] is True

    def test_compute_similarity_one_word_overlap(self):
        """Test compute_similarity with partial overlap."""
        from claim_agent.tools.logic import compute_similarity_impl

        result = json.loads(compute_similarity_impl("a b c", "a d e"))
        # 1 common word (a), 5 total unique words (a,b,c,d,e)
        assert result["similarity_score"] == 20.0  # 1/5 * 100
        assert result["is_duplicate"] is False

    def test_fetch_vehicle_value_known_vin(self):
        """Test fetch_vehicle_value with a known VIN from mock_db."""
        from claim_agent.tools.logic import fetch_vehicle_value_impl

        # Use a VIN that exists in the mock database
        result = json.loads(fetch_vehicle_value_impl("1HGBH41JXMN109186", 2021, "Honda", "Accord"))
        assert "value" in result
        assert result["value"] > 0

    def test_fetch_vehicle_value_unknown_vin(self):
        """Test fetch_vehicle_value with unknown VIN falls back to estimation."""
        from claim_agent.tools.logic import fetch_vehicle_value_impl

        result = json.loads(fetch_vehicle_value_impl("UNKNOWN_VIN", 2020, "Unknown", "Model"))
        assert "value" in result
        assert result["source"] == "mock_kbb_estimated"

    def test_fetch_vehicle_value_empty_inputs(self):
        """Test fetch_vehicle_value with empty inputs."""
        from claim_agent.tools.logic import fetch_vehicle_value_impl

        result = json.loads(fetch_vehicle_value_impl("", 0, "", ""))
        assert "value" in result
        assert result["value"] >= 2000  # Minimum value

    def test_evaluate_damage_empty_description(self):
        """Test evaluate_damage with empty description."""
        from claim_agent.tools.logic import evaluate_damage_impl

        result = json.loads(evaluate_damage_impl("", 1000))
        assert result["severity"] == "unknown"
        assert result["total_loss_candidate"] is False

    def test_evaluate_damage_keywords(self):
        """Test evaluate_damage with different severity keywords."""
        from claim_agent.tools.logic import evaluate_damage_impl

        # Fire keyword
        result = json.loads(evaluate_damage_impl("Vehicle caught fire.", 5000))
        assert result["total_loss_candidate"] is True
        assert result["severity"] == "high"

        # Frame damage
        result = json.loads(evaluate_damage_impl("Frame is bent.", 3000))
        assert result["total_loss_candidate"] is True

        # Destroyed
        result = json.loads(evaluate_damage_impl("Car destroyed in accident.", 8000))
        assert result["total_loss_candidate"] is True

    def test_generate_report_with_none_payout(self):
        """Test generate_report with None payout amount."""
        from claim_agent.tools.logic import generate_report_impl

        result = json.loads(generate_report_impl("CLM-001", "new", "open", "Summary", None))
        assert result["payout_amount"] is None

    def test_detect_fraud_indicators_empty_dict(self):
        """Test detect_fraud_indicators with empty claim data."""
        from claim_agent.tools.logic import detect_fraud_indicators_impl

        result = json.loads(detect_fraud_indicators_impl({}))
        assert result == []

    def test_detect_fraud_indicators_with_estimated_damage_string(self):
        """Test detect_fraud_indicators handles string estimated_damage."""
        from claim_agent.tools.logic import detect_fraud_indicators_impl

        result = json.loads(detect_fraud_indicators_impl({
            "incident_description": "Normal accident",
            "damage_description": "Bumper damage",
            "vin": "TEST",
            "incident_date": "2025-01-01",
            "estimated_damage": "5000",  # String instead of float
            "vehicle_year": 2020,
            "vehicle_make": "Honda",
            "vehicle_model": "Civic",
        }))
        assert isinstance(result, list)

    def test_parse_router_confidence_empty(self):
        """Test _parse_router_confidence with empty input."""
        from claim_agent.tools.logic import _parse_router_confidence

        assert _parse_router_confidence("") == 0.5
        assert _parse_router_confidence(None) == 0.5

    def test_parse_router_confidence_high(self):
        """Test _parse_router_confidence with clear output."""
        from claim_agent.tools.logic import _parse_router_confidence

        result = _parse_router_confidence("new\nClear first-time submission.")
        assert result >= 0.9

    def test_evaluate_escalation_no_claim_data(self):
        """Test evaluate_escalation with None claim data."""
        from claim_agent.tools.logic import evaluate_escalation_impl

        result = json.loads(evaluate_escalation_impl(None, "new", None, None))
        assert "needs_review" in result

    def test_compute_escalation_priority_empty(self):
        """Test compute_escalation_priority with empty inputs."""
        from claim_agent.tools.logic import compute_escalation_priority_impl

        result = json.loads(compute_escalation_priority_impl([], []))
        assert result["priority"] == "low"

    def test_analyze_claim_patterns_empty(self):
        """Test analyze_claim_patterns with empty data."""
        from claim_agent.tools.logic import analyze_claim_patterns_impl

        result = json.loads(analyze_claim_patterns_impl({}))
        assert result["patterns_detected"] == []
        assert result["pattern_score"] == 0

    def test_cross_reference_fraud_indicators_empty(self):
        """Test cross_reference_fraud_indicators with empty data."""
        from claim_agent.tools.logic import cross_reference_fraud_indicators_impl

        result = json.loads(cross_reference_fraud_indicators_impl({}))
        assert result["fraud_keywords_found"] == []
        assert result["risk_level"] == "low"

    def test_perform_fraud_assessment_empty(self):
        """Test perform_fraud_assessment with empty data."""
        from claim_agent.tools.logic import perform_fraud_assessment_impl

        result = json.loads(perform_fraud_assessment_impl({}))
        assert "Invalid claim data" in result["recommended_action"]

    def test_get_available_repair_shops_with_filters(self):
        """Test get_available_repair_shops with various filters."""
        from claim_agent.tools.logic import get_available_repair_shops_impl

        # Test with Tesla (EV) make
        result = json.loads(get_available_repair_shops_impl(vehicle_make="Tesla"))
        assert "shops" in result

        # Test with location filter (may not match)
        result = json.loads(get_available_repair_shops_impl(location="Unknown City"))
        assert "shops" in result

    def test_calculate_repair_estimate_with_various_damage(self):
        """Test calculate_repair_estimate with different damage types."""
        from claim_agent.tools.logic import calculate_repair_estimate_impl

        # Damage with paint/scratch
        result = json.loads(calculate_repair_estimate_impl(
            "Paint scratch on door",
            "Toyota",
            2020,
            "POL-001"
        ))
        assert result["labor_hours"] >= 2.0

        # Damage with alignment
        result = json.loads(calculate_repair_estimate_impl(
            "Wheel alignment needed after collision",
            "Honda",
            2021,
            "POL-001"
        ))
        assert "total_estimate" in result

    def test_create_parts_order_invalid_parts(self):
        """Test create_parts_order with invalid part IDs."""
        from claim_agent.tools.logic import create_parts_order_impl

        parts = [{"part_id": "INVALID-PART", "quantity": 1, "part_type": "oem"}]
        result = json.loads(create_parts_order_impl("CLM-TEST", parts, "SHOP-001"))
        assert result["success"] is False
        assert "No valid parts" in result["error"]

    def test_json_contains_query_recursive(self):
        """Test _json_contains_query with nested structures."""
        from claim_agent.tools.logic import _json_contains_query

        # Test with nested dict
        data = {"level1": {"level2": {"text": "search target"}}}
        assert _json_contains_query(data, "target") is True
        assert _json_contains_query(data, "notfound") is False

        # Test with list
        data = [{"text": "item1"}, {"text": "item2 target"}]
        assert _json_contains_query(data, "target") is True

        # Test with empty query
        assert _json_contains_query(data, "") is False
        assert _json_contains_query(data, "  ") is False
