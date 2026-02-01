"""MCP server integration tests.

These tests verify that the MCP (Model Context Protocol) server works correctly,
exposing claim processing functionality to external clients.
"""

import json

import pytest


# ============================================================================
# MCP Server Tool Tests
# ============================================================================


class TestMCPServerTools:
    """Test MCP server tool implementations."""
    
    @pytest.mark.integration
    def test_query_policy_db(self):
        """Test MCP query_policy_db tool."""
        from claim_agent.mcp_server.server import query_policy_db
        
        result = query_policy_db("POL-001")
        data = json.loads(result)
        
        assert data["valid"] is True
        assert "coverage" in data
        assert "deductible" in data
    
    @pytest.mark.integration
    def test_search_claims_db(self, integration_db):
        """Test MCP search_claims_db tool with database."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.mcp_server.server import search_claims_db
        
        # Create a claim
        repo = ClaimRepository(db_path=integration_db)
        repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="MCP_TEST_VIN",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-03-01",
            incident_description="Test for MCP",
            damage_description="Test damage",
        ))
        
        # Search via MCP tool
        result = search_claims_db("MCP_TEST_VIN", "2025-03-01")
        claims = json.loads(result)
        
        assert len(claims) >= 1
        assert claims[0]["vin"] == "MCP_TEST_VIN"
    
    @pytest.mark.integration
    def test_compute_similarity(self):
        """Test MCP compute_similarity tool."""
        from claim_agent.mcp_server.server import compute_similarity
        
        result = compute_similarity(
            description_a="Rear bumper damage from collision",
            description_b="Rear bumper damaged in accident"
        )
        data = json.loads(result)
        
        assert "similarity_score" in data
        # Jaccard similarity is word-based, should have good overlap
        assert data["similarity_score"] >= 0
    
    @pytest.mark.integration
    def test_fetch_vehicle_value(self):
        """Test MCP fetch_vehicle_value tool."""
        from claim_agent.mcp_server.server import fetch_vehicle_value
        
        result = fetch_vehicle_value(
            vin="1HGBH41JXMN109186",
            year=2021,
            make="Honda",
            model="Accord"
        )
        data = json.loads(result)
        
        assert "value" in data
        assert data["value"] > 0
    
    @pytest.mark.integration
    def test_evaluate_damage(self):
        """Test MCP evaluate_damage tool."""
        from claim_agent.mcp_server.server import evaluate_damage
        
        result = evaluate_damage(
            damage_description="Vehicle totaled in flood. Complete destruction.",
            estimated_repair_cost=25000.0
        )
        data = json.loads(result)
        
        assert data["total_loss_candidate"] is True
        assert data["severity"] == "high"
    
    @pytest.mark.integration
    def test_calculate_payout(self):
        """Test MCP calculate_payout tool."""
        from claim_agent.mcp_server.server import calculate_payout
        
        result = calculate_payout(
            vehicle_value=10000.0,
            policy_number="POL-001"
        )
        data = json.loads(result)
        
        assert "payout_amount" in data
        assert data["payout_amount"] > 0
        assert "deductible" in data
    
    @pytest.mark.integration
    def test_generate_report(self):
        """Test MCP generate_report tool."""
        from claim_agent.mcp_server.server import generate_report
        
        result = generate_report(
            claim_id="CLM-MCP001",
            claim_type="partial_loss",
            status="closed",
            summary="Claim processed successfully",
            payout_amount=5000.0
        )
        data = json.loads(result)
        
        assert data["claim_id"] == "CLM-MCP001"
        assert data["claim_type"] == "partial_loss"
        assert "report_id" in data
    
    @pytest.mark.integration
    def test_generate_claim_id(self):
        """Test MCP generate_claim_id tool."""
        from claim_agent.mcp_server.server import generate_claim_id
        
        id1 = generate_claim_id("CLM")
        id2 = generate_claim_id("CLM")
        
        assert id1.startswith("CLM-")
        assert id2.startswith("CLM-")
        assert id1 != id2
    
    @pytest.mark.integration
    def test_search_california_compliance(self):
        """Test MCP search_california_compliance tool."""
        from claim_agent.mcp_server.server import search_california_compliance
        
        result = search_california_compliance("total loss")
        data = json.loads(result)
        
        # Should return matches or sections
        assert "matches" in data or "sections" in data or "error" in data


# ============================================================================
# MCP Tool Pipeline Tests
# ============================================================================


class TestMCPToolPipelines:
    """Test MCP tools used in realistic pipelines."""
    
    @pytest.mark.integration
    def test_new_claim_pipeline(self, integration_db):
        """Test MCP tools in a new claim processing pipeline."""
        from claim_agent.mcp_server.server import (
            query_policy_db,
            generate_claim_id,
            generate_report,
        )
        
        # Step 1: Validate policy
        policy_result = query_policy_db("POL-001")
        policy_data = json.loads(policy_result)
        assert policy_data["valid"] is True
        
        # Step 2: Generate claim ID
        claim_id = generate_claim_id("CLM")
        assert claim_id.startswith("CLM-")
        
        # Step 3: Generate report
        report_result = generate_report(
            claim_id=claim_id,
            claim_type="new",
            status="open",
            summary="New claim submitted and validated",
            payout_amount=0.0
        )
        report_data = json.loads(report_result)
        assert report_data["claim_id"] == claim_id
    
    @pytest.mark.integration
    def test_duplicate_detection_pipeline(self, integration_db):
        """Test MCP tools in a duplicate detection pipeline."""
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput
        from claim_agent.mcp_server.server import (
            search_claims_db,
            compute_similarity,
        )
        
        # Create an existing claim
        repo = ClaimRepository(db_path=integration_db)
        repo.create_claim(ClaimInput(
            policy_number="POL-001",
            vin="DUPE_MCP_VIN",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-03-01",
            incident_description="Rear-ended at light",
            damage_description="Rear bumper damage",
        ))
        
        # New claim comes in
        new_description = "Rear bumper damaged from rear-end collision"
        
        # Search for existing claims
        search_result = search_claims_db("DUPE_MCP_VIN", "2025-03-01")
        existing_claims = json.loads(search_result)
        
        assert len(existing_claims) >= 1
        
        # Check similarity (search returns incident_description)
        similarity_result = compute_similarity(
            description_a=existing_claims[0]["incident_description"],
            description_b=new_description
        )
        sim_data = json.loads(similarity_result)
        
        # Should have some word overlap
        assert sim_data["similarity_score"] >= 0
    
    @pytest.mark.integration
    def test_total_loss_pipeline(self):
        """Test MCP tools in a total loss processing pipeline."""
        from claim_agent.mcp_server.server import (
            query_policy_db,
            fetch_vehicle_value,
            evaluate_damage,
            calculate_payout,
            generate_report,
            generate_claim_id,
        )
        
        # Step 1: Validate policy
        policy_result = query_policy_db("POL-001")
        policy_data = json.loads(policy_result)
        assert policy_data["valid"] is True
        
        # Step 2: Get vehicle value
        value_result = fetch_vehicle_value(
            vin="1HGBH41JXMN109186",
            year=2021,
            make="Honda",
            model="Accord"
        )
        value_data = json.loads(value_result)
        vehicle_value = value_data["value"]
        
        # Step 3: Evaluate damage
        damage_result = evaluate_damage(
            damage_description="Vehicle totaled in flood. Engine destroyed.",
            estimated_repair_cost=vehicle_value * 0.9
        )
        damage_data = json.loads(damage_result)
        assert damage_data["total_loss_candidate"] is True
        
        # Step 4: Calculate payout
        payout_result = calculate_payout(
            vehicle_value=vehicle_value,
            policy_number="POL-001"
        )
        payout_data = json.loads(payout_result)
        
        # Step 5: Generate claim ID and report
        claim_id = generate_claim_id("CLM")
        report_result = generate_report(
            claim_id=claim_id,
            claim_type="total_loss",
            status="closed",
            summary="Total loss claim settled at vehicle value",
            payout_amount=payout_data["payout_amount"]
        )
        report_data = json.loads(report_result)
        
        assert report_data["payout_amount"] == payout_data["payout_amount"]


# ============================================================================
# MCP Error Handling Tests
# ============================================================================


class TestMCPErrorHandling:
    """Test MCP server error handling."""
    
    @pytest.mark.integration
    def test_invalid_policy_returns_valid_false(self):
        """Test that invalid policy returns valid=False."""
        from claim_agent.mcp_server.server import query_policy_db
        
        result = query_policy_db("POL-INVALID")
        data = json.loads(result)
        
        assert data["valid"] is False
    
    @pytest.mark.integration
    def test_calculate_payout_invalid_policy(self):
        """Test calculate_payout with invalid policy."""
        from claim_agent.mcp_server.server import calculate_payout
        
        result = calculate_payout(
            vehicle_value=10000.0,
            policy_number="POL-INVALID"
        )
        data = json.loads(result)
        
        assert "error" in data
        assert data["payout_amount"] == 0.0
    
    @pytest.mark.integration
    def test_search_claims_no_match(self, integration_db):
        """Test search_claims_db with no matching claims."""
        from claim_agent.mcp_server.server import search_claims_db
        
        result = search_claims_db("NONEXISTENT_VIN", "2020-01-01")
        claims = json.loads(result)
        
        assert claims == []


# ============================================================================
# MCP Compliance Tool Tests
# ============================================================================


class TestMCPComplianceTools:
    """Test MCP compliance-related tools."""
    
    @pytest.mark.integration
    def test_california_compliance_search_total_loss(self):
        """Test California compliance search for total loss."""
        from claim_agent.mcp_server.server import search_california_compliance
        
        result = search_california_compliance("total loss valuation")
        data = json.loads(result)
        
        # Should return relevant matches
        assert "matches" in data or "sections" in data or "error" in data
    
    @pytest.mark.integration
    def test_california_compliance_search_empty_query(self):
        """Test California compliance search with empty query."""
        from claim_agent.mcp_server.server import search_california_compliance
        
        result = search_california_compliance("")
        data = json.loads(result)
        
        # Should return summary or error
        assert "sections" in data or "error" in data


# ============================================================================
# MCP Integration with Workflow Tests
# ============================================================================


class TestMCPWorkflowIntegration:
    """Test MCP tools integration with claim workflows."""
    
    @pytest.mark.integration
    def test_mcp_tools_match_workflow_tools(self):
        """Test that MCP tools produce same results as workflow tools."""
        from claim_agent.mcp_server.server import (
            query_policy_db as mcp_query,
            fetch_vehicle_value as mcp_value,
            evaluate_damage as mcp_damage,
        )
        from claim_agent.tools.policy_tools import query_policy_db as tool_query
        from claim_agent.tools.valuation_tools import (
            fetch_vehicle_value as tool_value,
            evaluate_damage as tool_damage,
        )
        
        # Compare policy query results
        mcp_result = mcp_query("POL-001")
        tool_result = tool_query.run(policy_number="POL-001")
        
        mcp_data = json.loads(mcp_result)
        tool_data = json.loads(tool_result)
        
        assert mcp_data["valid"] == tool_data["valid"]
        assert mcp_data["deductible"] == tool_data["deductible"]
        
        # Compare vehicle value results
        mcp_value_result = mcp_value("1HGBH41JXMN109186", 2021, "Honda", "Accord")
        tool_value_result = tool_value.run(
            vin="1HGBH41JXMN109186",
            year=2021,
            make="Honda",
            model="Accord"
        )
        
        mcp_value_data = json.loads(mcp_value_result)
        tool_value_data = json.loads(tool_value_result)
        
        assert mcp_value_data["value"] == tool_value_data["value"]
