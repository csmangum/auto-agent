"""Unit tests for tools/__init__.py lazy loading."""

import json

import pytest


class TestToolsLazyLoading:
    """Test lazy loading of tools via __getattr__."""

    def test_query_policy_db_lazy_load(self):
        """Test lazy loading of query_policy_db."""
        from claim_agent.tools import query_policy_db

        result = query_policy_db.run(policy_number="POL-001")
        data = json.loads(result)
        assert data["valid"] is True

    def test_search_claims_db_lazy_load(self):
        """Test lazy loading of search_claims_db."""
        from claim_agent.tools import search_claims_db

        result = search_claims_db.run(vin="VIN123", incident_date="2025-01-15")
        claims = json.loads(result)
        assert isinstance(claims, list)

    def test_compute_similarity_lazy_load(self):
        """Test lazy loading of compute_similarity."""
        from claim_agent.tools import compute_similarity

        result = compute_similarity.run(description_a="Test damage.", description_b="Test damage.")
        data = json.loads(result)
        assert data["similarity_score"] >= 80

    def test_fetch_vehicle_value_lazy_load(self):
        """Test lazy loading of fetch_vehicle_value."""
        from claim_agent.tools import fetch_vehicle_value

        result = fetch_vehicle_value.run(vin="VIN123", year=2021, make="Honda", model="Accord")
        data = json.loads(result)
        assert "value" in data

    def test_evaluate_damage_lazy_load(self):
        """Test lazy loading of evaluate_damage."""
        from claim_agent.tools import evaluate_damage

        result = evaluate_damage.run(damage_description="Minor dent.", estimated_repair_cost=500.0)
        data = json.loads(result)
        assert "severity" in data

    def test_calculate_payout_lazy_load(self):
        """Test lazy loading of calculate_payout."""
        from claim_agent.tools import calculate_payout

        result = calculate_payout.run(vehicle_value=10000.0, policy_number="POL-001")
        data = json.loads(result)
        assert "payout_amount" in data

    def test_generate_report_lazy_load(self):
        """Test lazy loading of generate_report."""
        from claim_agent.tools import generate_report

        result = generate_report.run(claim_id="CLM-TEST", claim_type="new", status="open", summary="Summary")
        data = json.loads(result)
        assert data["claim_id"] == "CLM-TEST"

    def test_generate_claim_id_lazy_load(self):
        """Test lazy loading of generate_claim_id."""
        from claim_agent.tools import generate_claim_id

        result = generate_claim_id.run(prefix="CLM")
        assert result.startswith("CLM-")

    def test_search_california_compliance_lazy_load(self):
        """Test lazy loading of search_california_compliance."""
        from claim_agent.tools import search_california_compliance

        result = search_california_compliance.run(query="")
        data = json.loads(result)
        assert "sections" in data or "error" in data

    def test_evaluate_escalation_lazy_load(self):
        """Test lazy loading of evaluate_escalation."""
        from claim_agent.tools import evaluate_escalation

        result = evaluate_escalation.run(claim_data='{"vin": "TEST"}', router_output="new")
        data = json.loads(result)
        assert "needs_review" in data

    def test_detect_fraud_indicators_lazy_load(self):
        """Test lazy loading of detect_fraud_indicators."""
        from claim_agent.tools import detect_fraud_indicators

        result = detect_fraud_indicators.run(claim_data='{"incident_description": "staged"}')
        indicators = json.loads(result)
        assert isinstance(indicators, list)

    def test_generate_escalation_report_lazy_load(self):
        """Test lazy loading of generate_escalation_report."""
        from claim_agent.tools import generate_escalation_report

        result = generate_escalation_report.run(
            claim_id="CLM-TEST",
            needs_review="true",
            escalation_reasons="[]",
            priority="low",
            recommended_action="Review.",
        )
        assert "CLM-TEST" in result

    def test_analyze_claim_patterns_lazy_load(self):
        """Test lazy loading of analyze_claim_patterns."""
        from claim_agent.tools import analyze_claim_patterns

        result = analyze_claim_patterns.run(claim_data="{}")
        data = json.loads(result)
        assert "patterns_detected" in data

    def test_cross_reference_fraud_indicators_lazy_load(self):
        """Test lazy loading of cross_reference_fraud_indicators."""
        from claim_agent.tools import cross_reference_fraud_indicators

        result = cross_reference_fraud_indicators.run(claim_data="{}")
        data = json.loads(result)
        assert "fraud_keywords_found" in data

    def test_perform_fraud_assessment_lazy_load(self):
        """Test lazy loading of perform_fraud_assessment."""
        from claim_agent.tools import perform_fraud_assessment

        result = perform_fraud_assessment.run(claim_data='{"vin": "TEST"}')
        data = json.loads(result)
        assert "fraud_score" in data

    def test_generate_fraud_report_lazy_load(self):
        """Test lazy loading of generate_fraud_report."""
        from claim_agent.tools import generate_fraud_report

        result = generate_fraud_report.run(
            claim_id="CLM-TEST",
            fraud_likelihood="low",
            fraud_score="0",
            fraud_indicators="[]",
            recommended_action="Process.",
        )
        assert "CLM-TEST" in result

    def test_get_available_repair_shops_lazy_load(self):
        """Test lazy loading of get_available_repair_shops."""
        from claim_agent.tools import get_available_repair_shops

        result = get_available_repair_shops.run()
        data = json.loads(result)
        assert "shops" in data

    def test_assign_repair_shop_lazy_load(self):
        """Test lazy loading of assign_repair_shop."""
        from claim_agent.tools import assign_repair_shop

        result = assign_repair_shop.run(claim_id="CLM-TEST", shop_id="SHOP-001", estimated_repair_days=5)
        data = json.loads(result)
        assert "success" in data

    def test_get_parts_catalog_lazy_load(self):
        """Test lazy loading of get_parts_catalog."""
        from claim_agent.tools import get_parts_catalog

        result = get_parts_catalog.run(damage_description="bumper damage", vehicle_make="Honda", part_type_preference="aftermarket")
        data = json.loads(result)
        assert "parts" in data

    def test_create_parts_order_lazy_load(self):
        """Test lazy loading of create_parts_order."""
        from claim_agent.tools import create_parts_order

        parts = [{"part_id": "PART-BUMPER-FRONT", "quantity": 1, "part_type": "aftermarket"}]
        result = create_parts_order.run(claim_id="CLM-TEST", parts=parts, shop_id="SHOP-001")
        data = json.loads(result)
        assert "success" in data

    def test_calculate_repair_estimate_lazy_load(self):
        """Test lazy loading of calculate_repair_estimate."""
        from claim_agent.tools import calculate_repair_estimate

        result = calculate_repair_estimate.run(damage_description="bumper", vehicle_make="Honda", vehicle_year=2021, policy_number="POL-001")
        data = json.loads(result)
        assert "total_estimate" in data

    def test_generate_repair_authorization_lazy_load(self):
        """Test lazy loading of generate_repair_authorization."""
        from claim_agent.tools import generate_repair_authorization

        result = generate_repair_authorization.run(
            claim_id="CLM-TEST",
            shop_id="SHOP-001",
            total_estimate=2000.0,
            parts_cost=800.0,
            labor_cost=1200.0,
            deductible=500.0,
            customer_pays=500.0,
            insurance_pays=1500.0,
        )
        data = json.loads(result)
        assert "authorization_id" in data

    def test_invalid_attribute_raises(self):
        """Test that invalid attribute raises AttributeError."""
        with pytest.raises(AttributeError, match="nonexistent_tool"):
            from claim_agent import tools
            _ = tools.nonexistent_tool


class TestClaimsToolsWrapper:
    """Test claims_tools.py wrappers."""

    def test_search_claims_db_wrapper(self):
        """Test search_claims_db wrapper."""
        from claim_agent.tools.claims_tools import search_claims_db

        result = search_claims_db.run(vin="VIN123", incident_date="2025-01-15")
        claims = json.loads(result)
        assert isinstance(claims, list)

    def test_compute_similarity_wrapper(self):
        """Test compute_similarity wrapper."""
        from claim_agent.tools.claims_tools import compute_similarity

        result = compute_similarity.run(description_a="damage", description_b="damage")
        data = json.loads(result)
        assert data["similarity_score"] >= 80


class TestDocumentToolsWrapper:
    """Test document_tools.py wrappers."""

    def test_generate_report_wrapper(self):
        """Test generate_report wrapper."""
        from claim_agent.tools.document_tools import generate_report

        result = generate_report.run(claim_id="CLM-001", claim_type="new", status="open", summary="Summary", payout_amount=5000.0)
        data = json.loads(result)
        assert data["claim_id"] == "CLM-001"

    def test_generate_claim_id_wrapper(self):
        """Test generate_claim_id wrapper."""
        from claim_agent.tools.document_tools import generate_claim_id

        result = generate_claim_id.run(prefix="TEST")
        assert result.startswith("TEST-")


class TestValuationToolsWrapper:
    """Test valuation_tools.py wrappers."""

    def test_fetch_vehicle_value_wrapper(self):
        """Test fetch_vehicle_value wrapper."""
        from claim_agent.tools.valuation_tools import fetch_vehicle_value

        result = fetch_vehicle_value.run(vin="VIN123", year=2021, make="Honda", model="Accord")
        data = json.loads(result)
        assert "value" in data

    def test_evaluate_damage_wrapper(self):
        """Test evaluate_damage wrapper."""
        from claim_agent.tools.valuation_tools import evaluate_damage

        result = evaluate_damage.run(damage_description="flood damage total loss", estimated_repair_cost=20000.0)
        data = json.loads(result)
        assert data["total_loss_candidate"] is True

    def test_calculate_payout_wrapper(self):
        """Test calculate_payout wrapper."""
        from claim_agent.tools.valuation_tools import calculate_payout

        result = calculate_payout.run(vehicle_value=15000.0, policy_number="POL-001")
        data = json.loads(result)
        assert data["payout_amount"] == 14500.0


class TestPolicyToolsWrapper:
    """Test policy_tools.py wrappers."""

    def test_query_policy_db_wrapper(self):
        """Test query_policy_db wrapper."""
        from claim_agent.tools.policy_tools import query_policy_db

        result = query_policy_db.run(policy_number="POL-001")
        data = json.loads(result)
        assert data["valid"] is True


class TestPartialLossToolsWrapper:
    """Test partial_loss_tools.py wrappers."""

    def test_get_available_repair_shops_wrapper(self):
        """Test get_available_repair_shops wrapper."""
        from claim_agent.tools.partial_loss_tools import get_available_repair_shops

        result = get_available_repair_shops.run()
        data = json.loads(result)
        assert "shops" in data

    def test_assign_repair_shop_wrapper(self):
        """Test assign_repair_shop wrapper."""
        from claim_agent.tools.partial_loss_tools import assign_repair_shop

        result = assign_repair_shop.run(claim_id="CLM-TEST", shop_id="SHOP-001", estimated_repair_days=5)
        data = json.loads(result)
        assert data["success"] is True

    def test_get_parts_catalog_wrapper(self):
        """Test get_parts_catalog wrapper."""
        from claim_agent.tools.partial_loss_tools import get_parts_catalog

        result = get_parts_catalog.run(damage_description="front bumper", vehicle_make="Honda", part_type_preference="aftermarket")
        data = json.loads(result)
        assert "parts" in data

    def test_create_parts_order_wrapper(self):
        """Test create_parts_order wrapper."""
        from claim_agent.tools.partial_loss_tools import create_parts_order

        parts = [{"part_id": "PART-BUMPER-FRONT", "quantity": 1, "part_type": "oem"}]
        result = create_parts_order.run(claim_id="CLM-TEST", parts=parts, shop_id="SHOP-001")
        data = json.loads(result)
        assert data["success"] is True

    def test_calculate_repair_estimate_wrapper(self):
        """Test calculate_repair_estimate wrapper."""
        from claim_agent.tools.partial_loss_tools import calculate_repair_estimate

        result = calculate_repair_estimate.run(damage_description="front bumper", vehicle_make="Honda", vehicle_year=2021, policy_number="POL-001", shop_id="SHOP-001")
        data = json.loads(result)
        assert "total_estimate" in data

    def test_generate_repair_authorization_wrapper(self):
        """Test generate_repair_authorization wrapper."""
        from claim_agent.tools.partial_loss_tools import generate_repair_authorization

        result = generate_repair_authorization.run(
            claim_id="CLM-TEST",
            shop_id="SHOP-001",
            total_estimate=2000.0,
            parts_cost=800.0,
            labor_cost=1200.0,
            deductible=500.0,
            customer_pays=500.0,
            insurance_pays=1500.0,
            customer_approved=True,
        )
        data = json.loads(result)
        assert data["authorization_status"] == "approved"
