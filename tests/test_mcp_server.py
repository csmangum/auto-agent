"""Unit tests for MCP server tools."""

import json
import os
import tempfile
from pathlib import Path

# Point to project data for mock_db
os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))

from claim_agent.mcp_server.server import (
    query_policy_db,
    search_claims_db,
    compute_similarity,
    fetch_vehicle_value,
    evaluate_damage,
    calculate_payout,
    generate_report,
    generate_claim_id,
    search_california_compliance,
)


class TestMcpServerTools:
    """Test MCP server tool wrappers."""

    def test_query_policy_db_valid(self):
        """Test query_policy_db with valid policy."""
        result = query_policy_db("POL-001")
        data = json.loads(result)
        assert data["valid"] is True
        assert "coverage" in data
        assert data["deductible"] == 500

    def test_query_policy_db_invalid(self):
        """Test query_policy_db with invalid policy."""
        result = query_policy_db("POL-999")
        data = json.loads(result)
        assert data["valid"] is False

    def test_search_claims_db_empty(self):
        """Test search_claims_db with no matches."""
        from claim_agent.db.database import init_db

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        prev = os.environ.get("CLAIMS_DB_PATH")
        try:
            init_db(path)
            os.environ["CLAIMS_DB_PATH"] = path
            result = search_claims_db("UNKNOWN_VIN", "2020-01-01")
            claims = json.loads(result)
            assert claims == []
        finally:
            os.unlink(path)
            if prev is None:
                os.environ.pop("CLAIMS_DB_PATH", None)
            else:
                os.environ["CLAIMS_DB_PATH"] = prev

    def test_search_claims_db_with_match(self):
        """Test search_claims_db with a matching claim."""
        from claim_agent.db.database import init_db
        from claim_agent.db.repository import ClaimRepository
        from claim_agent.models.claim import ClaimInput

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        prev = os.environ.get("CLAIMS_DB_PATH")
        try:
            init_db(path)
            os.environ["CLAIMS_DB_PATH"] = path
            repo = ClaimRepository(db_path=path)
            repo.create_claim(
                ClaimInput(
                    policy_number="POL-001",
                    vin="TEST_VIN_123",
                    vehicle_year=2021,
                    vehicle_make="Honda",
                    vehicle_model="Accord",
                    incident_date="2025-03-15",
                    incident_description="Test incident.",
                    damage_description="Test damage.",
                )
            )
            result = search_claims_db("TEST_VIN_123", "2025-03-15")
            claims = json.loads(result)
            assert len(claims) >= 1
            assert claims[0]["vin"] == "TEST_VIN_123"
        finally:
            os.unlink(path)
            if prev is None:
                os.environ.pop("CLAIMS_DB_PATH", None)
            else:
                os.environ["CLAIMS_DB_PATH"] = prev

    def test_compute_similarity_high(self):
        """Test compute_similarity with identical descriptions."""
        result = compute_similarity("Rear bumper damage.", "Rear bumper damage.")
        data = json.loads(result)
        assert data["similarity_score"] >= 80
        assert data["is_duplicate"] is True

    def test_compute_similarity_low(self):
        """Test compute_similarity with different descriptions."""
        result = compute_similarity("Parking lot scratch.", "Flood damage total loss.")
        data = json.loads(result)
        assert data["similarity_score"] < 80
        assert data["is_duplicate"] is False

    def test_fetch_vehicle_value(self):
        """Test fetch_vehicle_value returns valuation."""
        result = fetch_vehicle_value("1HGBH41JXMN109186", 2021, "Honda", "Accord")
        data = json.loads(result)
        assert "value" in data
        assert data["value"] > 0
        assert "condition" in data

    def test_evaluate_damage_total_loss(self):
        """Test evaluate_damage identifies total loss."""
        result = evaluate_damage("Vehicle totaled in flood. Complete destruction.", 25000.0)
        data = json.loads(result)
        assert data["total_loss_candidate"] is True
        assert data["severity"] == "high"

    def test_evaluate_damage_minor(self):
        """Test evaluate_damage for minor damage."""
        result = evaluate_damage("Small dent on door.", 500.0)
        data = json.loads(result)
        assert data["total_loss_candidate"] is False
        assert data["severity"] == "medium"

    def test_calculate_payout_valid(self):
        """Test calculate_payout with valid policy."""
        result = calculate_payout(15000.0, "POL-001")
        data = json.loads(result)
        assert data["payout_amount"] == 14500.0  # 15000 - 500 deductible
        assert data["deductible"] == 500

    def test_calculate_payout_invalid_policy(self):
        """Test calculate_payout with invalid policy."""
        result = calculate_payout(15000.0, "POL-999")
        data = json.loads(result)
        assert "error" in data
        assert data["payout_amount"] == 0.0

    def test_generate_report(self):
        """Test generate_report creates report structure."""
        result = generate_report("CLM-TEST001", "new", "open", "Test summary", 5000.0)
        data = json.loads(result)
        assert data["claim_id"] == "CLM-TEST001"
        assert data["claim_type"] == "new"
        assert data["status"] == "open"
        assert data["summary"] == "Test summary"
        assert data["payout_amount"] == 5000.0
        assert "report_id" in data

    def test_generate_claim_id(self):
        """Test generate_claim_id creates unique IDs."""
        id1 = generate_claim_id("CLM")
        id2 = generate_claim_id("CLM")
        assert id1.startswith("CLM-")
        assert id2.startswith("CLM-")
        assert id1 != id2

    def test_generate_claim_id_custom_prefix(self):
        """Test generate_claim_id with custom prefix."""
        result = generate_claim_id("TEST")
        assert result.startswith("TEST-")

    def test_search_california_compliance_empty(self):
        """Test search_california_compliance with empty query returns summary."""
        result = search_california_compliance("")
        data = json.loads(result)
        assert "sections" in data or "error" in data

    def test_search_california_compliance_query(self):
        """Test search_california_compliance with a query."""
        result = search_california_compliance("total loss")
        data = json.loads(result)
        assert "matches" in data or "error" in data
