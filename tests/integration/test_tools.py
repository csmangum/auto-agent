"""Tools pipeline integration tests.

These tests verify that the claim processing tools work correctly together,
testing realistic scenarios where multiple tools are used in sequence.
"""

import json

import pytest


# ============================================================================
# Policy Tools Integration
# ============================================================================


class TestPolicyTools:
    """Test policy-related tools integration."""
    
    @pytest.mark.integration
    def test_query_policy_db_with_valid_policy(self):
        """Test querying a valid policy returns expected data."""
        from claim_agent.tools.policy_tools import query_policy_db
        
        result = query_policy_db.run(policy_number="POL-001")
        data = json.loads(result)
        
        assert data["valid"] is True
        assert "coverage" in data
        assert "deductible" in data
        assert data["deductible"] > 0
    
    @pytest.mark.integration
    def test_query_policy_db_with_invalid_policy(self):
        """Test querying an invalid policy returns valid=False."""
        from claim_agent.tools.policy_tools import query_policy_db
        
        result = query_policy_db.run(policy_number="POL-INVALID")
        data = json.loads(result)
        
        assert data["valid"] is False
    
    @pytest.mark.integration
    def test_policy_affects_payout_calculation(self):
        """Test that policy deductible affects payout calculation."""
        from claim_agent.tools.policy_tools import query_policy_db
        from claim_agent.tools.valuation_tools import calculate_payout
        
        # Get policy details first
        policy_result = query_policy_db.run(policy_number="POL-001")
        policy_data = json.loads(policy_result)
        deductible = policy_data["deductible"]
        
        # Calculate payout (vehicle_value is the parameter name)
        vehicle_value = 5000.0
        payout_result = calculate_payout.run(
            vehicle_value=vehicle_value,
            policy_number="POL-001"
        )
        payout_data = json.loads(payout_result)
        
        # Verify payout = vehicle_value - deductible
        assert payout_data["payout_amount"] == vehicle_value - deductible


# ============================================================================
# Claims Tools Integration
# ============================================================================


class TestClaimsTools:
    """Test claims-related tools integration."""
    
    @pytest.mark.integration
    def test_search_claims_db_finds_created_claim(self, integration_db):
        """Test that search_claims_db finds claims in the database."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.tools.claims_tools import search_claims_db
        
        # Create a claim first
        repo = ClaimRepository(db_path=integration_db)
        repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="TEST_SEARCH_VIN",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-02-15",
            incident_description="Test incident",
            damage_description="Test damage",
        ))
        
        # Search for it
        result = search_claims_db.run(
            vin="TEST_SEARCH_VIN",
            incident_date="2025-02-15"
        )
        claims = json.loads(result)
        
        assert len(claims) >= 1
        assert claims[0]["vin"] == "TEST_SEARCH_VIN"
    
    @pytest.mark.integration
    def test_compute_similarity_identical_descriptions(self):
        """Test similarity computation with identical descriptions."""
        from claim_agent.tools.claims_tools import compute_similarity
        
        desc = "Rear bumper damaged from rear-end collision at stoplight."
        result = compute_similarity.run(description_a=desc, description_b=desc)
        data = json.loads(result)
        
        assert data["similarity_score"] == 100.0
        assert data["is_duplicate"] is True
    
    @pytest.mark.integration
    def test_compute_similarity_different_descriptions(self):
        """Test similarity computation with different descriptions."""
        from claim_agent.tools.claims_tools import compute_similarity
        
        result = compute_similarity.run(
            description_a="Minor scratch on front bumper from parking lot.",
            description_b="Total loss from flood damage. Vehicle submerged."
        )
        data = json.loads(result)
        
        assert data["similarity_score"] < 50
        assert data["is_duplicate"] is False
    
    @pytest.mark.integration
    def test_duplicate_detection_workflow(self, integration_db):
        """Test complete duplicate detection workflow."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.tools.claims_tools import search_claims_db, compute_similarity
        
        repo = ClaimRepository(db_path=integration_db)
        
        # Create original claim
        repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="DUPE_TEST_VIN",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-01-15",
            incident_description="Rear-ended at intersection",
            damage_description="Rear bumper and trunk damage",
        ))
        
        # New claim comes in with same VIN and date
        new_claim_desc = "Rear bumper damage from being rear-ended"
        
        # Step 1: Search for existing claims
        search_result = search_claims_db.run(
            vin="DUPE_TEST_VIN",
            incident_date="2025-01-15"
        )
        existing_claims = json.loads(search_result)
        
        assert len(existing_claims) >= 1
        
        # Step 2: Check similarity (search returns incident_description)
        similarity_result = compute_similarity.run(
            description_a=existing_claims[0]["incident_description"],
            description_b=new_claim_desc
        )
        sim_data = json.loads(similarity_result)
        
        # Should have some overlap (words like "rear-ended", "bumper")
        assert sim_data["similarity_score"] > 0


# ============================================================================
# Valuation Tools Integration
# ============================================================================


class TestValuationTools:
    """Test valuation-related tools integration."""
    
    @pytest.mark.integration
    def test_fetch_vehicle_value(self):
        """Test fetching vehicle value."""
        from claim_agent.tools.valuation_tools import fetch_vehicle_value
        
        result = fetch_vehicle_value.run(
            vin="1HGBH41JXMN109186",
            year=2021,
            make="Honda",
            model="Accord"
        )
        data = json.loads(result)
        
        assert "value" in data
        assert data["value"] > 0
        assert "condition" in data
    
    @pytest.mark.integration
    def test_evaluate_damage_total_loss(self):
        """Test damage evaluation identifies total loss."""
        from claim_agent.tools.valuation_tools import evaluate_damage
        
        result = evaluate_damage.run(
            damage_description="Vehicle completely destroyed in flood. Engine and interior ruined.",
            estimated_repair_cost=20000.0
        )
        data = json.loads(result)
        
        assert data["total_loss_candidate"] is True
        assert data["severity"] == "high"
    
    @pytest.mark.integration
    def test_evaluate_damage_minor(self):
        """Test damage evaluation identifies minor damage."""
        from claim_agent.tools.valuation_tools import evaluate_damage
        
        result = evaluate_damage.run(
            damage_description="Small dent on driver door.",
            estimated_repair_cost=500.0
        )
        data = json.loads(result)
        
        assert data["total_loss_candidate"] is False
    
    @pytest.mark.integration
    def test_total_loss_valuation_workflow(self):
        """Test complete total loss valuation workflow."""
        from claim_agent.tools.valuation_tools import (
            fetch_vehicle_value,
            evaluate_damage,
            calculate_payout,
        )
        
        # Step 1: Get vehicle value
        value_result = fetch_vehicle_value.run(
            vin="1HGBH41JXMN109186",
            year=2021,
            make="Honda",
            model="Accord"
        )
        value_data = json.loads(value_result)
        vehicle_value = value_data["value"]
        
        # Step 2: Evaluate damage
        damage_result = evaluate_damage.run(
            damage_description="Vehicle totaled in collision. Frame damage.",
            estimated_repair_cost=vehicle_value * 0.8  # 80% of value
        )
        damage_data = json.loads(damage_result)
        
        assert damage_data["total_loss_candidate"] is True
        
        # Step 3: Calculate payout (if total loss, payout = vehicle value - deductible)
        payout_result = calculate_payout.run(
            vehicle_value=vehicle_value,
            policy_number="POL-001"
        )
        payout_data = json.loads(payout_result)
        
        assert payout_data["payout_amount"] > 0


# ============================================================================
# Fraud Tools Integration
# ============================================================================


class TestFraudTools:
    """Test fraud detection tools integration."""
    
    @pytest.mark.integration
    def test_analyze_claim_patterns(self):
        """Test claim pattern analysis."""
        from claim_agent.tools.fraud_tools import analyze_claim_patterns
        
        result = analyze_claim_patterns.run(
            claim_data=json.dumps({
                "policy_number": "POL-001",
                "vin": "TEST_VIN",
                "incident_description": "Staged accident at intersection",
                "damage_description": "Inflated damage claims",
                "estimated_damage": 50000,
            })
        )
        data = json.loads(result)
        
        assert "pattern_score" in data or "patterns_detected" in data
    
    @pytest.mark.integration
    def test_cross_reference_fraud_indicators(self):
        """Test fraud indicator cross-referencing."""
        from claim_agent.tools.fraud_tools import cross_reference_fraud_indicators
        
        result = cross_reference_fraud_indicators.run(
            claim_data=json.dumps({
                "policy_number": "POL-001",
                "vin": "FRAUD_TEST_VIN",
                "incident_description": "Suspicious accident with no witnesses",
            })
        )
        data = json.loads(result)
        
        assert "fraud_keywords_found" in data or "risk_level" in data or "cross_reference_score" in data
    
    @pytest.mark.integration
    def test_fraud_detection_workflow(self):
        """Test complete fraud detection workflow."""
        from claim_agent.tools.fraud_tools import (
            analyze_claim_patterns,
            perform_fraud_assessment,
            generate_fraud_report,
        )
        
        claim_data = {
            "policy_number": "POL-001",
            "vin": "JM1BL1S58A1234568",
            "incident_description": "Staged accident with exaggerated injuries",
            "damage_description": "Inflated damage claims far exceeding actual damage",
            "estimated_damage": 50000,
        }
        
        # Step 1: Analyze patterns
        patterns_result = analyze_claim_patterns.run(
            claim_data=json.dumps(claim_data)
        )
        patterns_data = json.loads(patterns_result)
        assert isinstance(patterns_data, dict)
        
        # Step 2: Perform assessment
        assessment_result = perform_fraud_assessment.run(
            claim_data=json.dumps(claim_data)
        )
        assessment_data = json.loads(assessment_result)
        
        assert "fraud_score" in assessment_data or "fraud_likelihood" in assessment_data
        
        # Step 3: Generate report (uses specific string parameters)
        report_result = generate_fraud_report.run(
            claim_id="CLM-TEST001",
            fraud_likelihood=assessment_data.get("fraud_likelihood", "low"),
            fraud_score=str(assessment_data.get("fraud_score", 0)),
            fraud_indicators=json.dumps(assessment_data.get("fraud_indicators", [])),
            recommended_action=assessment_data.get("recommended_action", "Review claim"),
            siu_referral=str(assessment_data.get("siu_referral", False)).lower(),
            should_block=str(assessment_data.get("should_block", False)).lower(),
        )
        
        # generate_fraud_report returns a formatted string report, not JSON
        assert "CLM-TEST001" in report_result


# ============================================================================
# Partial Loss Tools Integration
# ============================================================================


class TestPartialLossTools:
    """Test partial loss processing tools integration."""
    
    @pytest.mark.integration
    def test_get_available_repair_shops(self):
        """Test getting available repair shops."""
        from claim_agent.tools.partial_loss_tools import get_available_repair_shops
        
        result = get_available_repair_shops.run(location="San Francisco, CA")
        data = json.loads(result)
        
        assert "shops" in data
        assert len(data["shops"]) > 0
    
    @pytest.mark.integration
    def test_calculate_repair_estimate(self):
        """Test repair estimate calculation."""
        from claim_agent.tools.partial_loss_tools import calculate_repair_estimate
        
        result = calculate_repair_estimate.run(
            damage_description="Front bumper crack and dent",
            vehicle_make="Honda",
            vehicle_year=2021,
            policy_number="POL-001",
        )
        data = json.loads(result)
        
        assert "total_estimate" in data
        assert "parts_cost" in data or "labor_cost" in data
    
    @pytest.mark.integration
    def test_partial_loss_workflow(self):
        """Test complete partial loss workflow."""
        from claim_agent.tools.partial_loss_tools import (
            get_available_repair_shops,
            calculate_repair_estimate,
            generate_repair_authorization,
        )
        
        # Step 1: Get repair shops
        shops_result = get_available_repair_shops.run(location="Los Angeles, CA")
        shops_data = json.loads(shops_result)
        
        # Note: may be empty if no shops match location
        if shops_data["shop_count"] == 0:
            shops_result = get_available_repair_shops.run()  # Get any available
            shops_data = json.loads(shops_result)
        
        if shops_data["shop_count"] == 0:
            pytest.skip("No repair shops available in mock data")
        
        selected_shop = shops_data["shops"][0]
        
        # Step 2: Calculate estimate
        estimate_result = calculate_repair_estimate.run(
            damage_description="Rear bumper and taillight damage",
            vehicle_make="Honda",
            vehicle_year=2021,
            policy_number="POL-001",
            shop_id=selected_shop.get("shop_id"),
        )
        estimate_data = json.loads(estimate_result)
        
        # Step 3: Generate authorization (with all required parameters)
        auth_result = generate_repair_authorization.run(
            claim_id="CLM-PARTIAL001",
            shop_id=selected_shop.get("shop_id", "SHOP-001"),
            total_estimate=estimate_data.get("total_estimate", 2000),
            parts_cost=estimate_data.get("parts_cost", 1000),
            labor_cost=estimate_data.get("labor_cost", 500),
            deductible=estimate_data.get("deductible", 500),
            customer_pays=estimate_data.get("customer_pays", 500),
            insurance_pays=estimate_data.get("insurance_pays", 1500),
            customer_approved=True,
        )
        auth_data = json.loads(auth_result)
        
        assert "authorization_id" in auth_data


# ============================================================================
# Escalation Tools Integration
# ============================================================================


class TestEscalationTools:
    """Test escalation tools integration."""
    
    @pytest.mark.integration
    def test_evaluate_escalation_high_value(self):
        """Test escalation evaluation for high value claims."""
        from claim_agent.tools.escalation_tools import evaluate_escalation
        
        result = evaluate_escalation.run(
            claim_data=json.dumps({
                "policy_number": "POL-001",
                "estimated_damage": 100000,
            }),
            router_output="new",
            similarity_score=None,
            payout_amount=100000
        )
        data = json.loads(result)
        
        # High value should trigger escalation
        assert data.get("needs_review") is True
        assert "high_value" in str(data.get("escalation_reasons", [])).lower() or \
               "amount" in str(data.get("escalation_reasons", [])).lower()
    
    @pytest.mark.integration
    def test_detect_fraud_indicators(self):
        """Test fraud indicator detection."""
        from claim_agent.tools.escalation_tools import detect_fraud_indicators
        
        result = detect_fraud_indicators.run(
            claim_data=json.dumps({
                "incident_description": "Staged accident with suspicious circumstances",
                "damage_description": "Exaggerated damage claims",
            })
        )
        # detect_fraud_indicators returns a JSON array
        data = json.loads(result)
        
        assert isinstance(data, list)
    
    @pytest.mark.integration
    def test_generate_escalation_report(self):
        """Test escalation report generation."""
        from claim_agent.tools.escalation_tools import generate_escalation_report
        
        # generate_escalation_report takes string parameters
        result = generate_escalation_report.run(
            claim_id="CLM-ESC001",
            needs_review="true",
            escalation_reasons=json.dumps(["high_value", "fraud_indicators"]),
            priority="high",
            recommended_action="Review claim manually. Verify valuation."
        )
        
        # Returns a formatted string report, not JSON
        assert "CLM-ESC001" in result
        assert "high" in result.lower()


# ============================================================================
# Document Tools Integration
# ============================================================================


class TestDocumentTools:
    """Test document generation tools integration."""
    
    @pytest.mark.integration
    def test_generate_claim_id(self):
        """Test claim ID generation."""
        from claim_agent.tools.document_tools import generate_claim_id
        
        ids = set()
        for _ in range(10):
            result = generate_claim_id.run(prefix="CLM")
            ids.add(result)
        
        # All IDs should be unique
        assert len(ids) == 10
        # All should have correct prefix
        assert all(id.startswith("CLM-") for id in ids)
    
    @pytest.mark.integration
    def test_generate_report(self):
        """Test report generation."""
        from claim_agent.tools.document_tools import generate_report
        
        result = generate_report.run(
            claim_id="CLM-RPT001",
            claim_type="partial_loss",
            status="closed",
            summary="Claim processed and resolved successfully",
            payout_amount=3500.0
        )
        data = json.loads(result)
        
        assert data["claim_id"] == "CLM-RPT001"
        assert data["claim_type"] == "partial_loss"
        assert data["status"] == "closed"
        assert data["payout_amount"] == 3500.0
        assert "report_id" in data


# ============================================================================
# Compliance Tools Integration
# ============================================================================


class TestComplianceTools:
    """Test compliance tools integration."""
    
    @pytest.mark.integration
    def test_search_california_compliance(self):
        """Test California compliance search."""
        from claim_agent.tools.compliance_tools import search_california_compliance
        
        result = search_california_compliance.run(query="total loss")
        data = json.loads(result)
        
        # Should return matching sections or error
        assert "matches" in data or "sections" in data or "error" in data
    
    @pytest.mark.integration
    def test_compliance_workflow(self):
        """Test compliance checking in claim workflow context."""
        from claim_agent.tools.compliance_tools import search_california_compliance
        from claim_agent.tools.valuation_tools import evaluate_damage
        
        # Evaluate damage
        damage_result = evaluate_damage.run(
            damage_description="Vehicle totaled in flood",
            estimated_repair_cost=20000.0
        )
        damage_data = json.loads(damage_result)
        
        # If total loss, check compliance requirements
        if damage_data["total_loss_candidate"]:
            compliance_result = search_california_compliance.run(
                query="total loss settlement requirements"
            )
            compliance_data = json.loads(compliance_result)
            
            # Should get compliance information
            assert compliance_data is not None
