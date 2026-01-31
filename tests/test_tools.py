"""Unit tests for claim tools."""

import json
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Point to project data for mock_db
os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))


def test_query_policy_db_found():
    from claim_agent.tools.logic import query_policy_db_impl

    result = query_policy_db_impl("POL-001")
    data = json.loads(result)
    assert data["valid"] is True
    assert "coverage" in data
    assert data["deductible"] == 500


def test_query_policy_db_not_found():
    from claim_agent.tools.logic import query_policy_db_impl

    result = query_policy_db_impl("POL-999")
    data = json.loads(result)
    assert data["valid"] is False


def test_search_claims_db():
    from claim_agent.tools.logic import search_claims_db_impl

    result = search_claims_db_impl("1HGBH41JXMN109186", "2025-01-15")
    claims = json.loads(result)
    assert isinstance(claims, list)
    assert len(claims) >= 1
    assert claims[0]["vin"] == "1HGBH41JXMN109186"


def test_search_claims_db_empty():
    from claim_agent.tools.logic import search_claims_db_impl

    result = search_claims_db_impl("UNKNOWN_VIN", "2020-01-01")
    claims = json.loads(result)
    assert claims == []


def test_compute_similarity_high():
    from claim_agent.tools.logic import compute_similarity_impl

    a = "Rear-ended at stoplight. Damage to rear bumper and trunk."
    b = "Rear-ended at stoplight. Damage to rear bumper and trunk."
    result = json.loads(compute_similarity_impl(a, b))
    assert result["similarity_score"] >= 80
    assert result["is_duplicate"] is True


def test_compute_similarity_low():
    from claim_agent.tools.logic import compute_similarity_impl

    a = "Parking lot scratch."
    b = "Total loss flood damage."
    result = json.loads(compute_similarity_impl(a, b))
    assert result["similarity_score"] < 80
    assert result["is_duplicate"] is False


def test_fetch_vehicle_value():
    from claim_agent.tools.logic import fetch_vehicle_value_impl

    result = fetch_vehicle_value_impl("1HGBH41JXMN109186", 2021, "Honda", "Accord")
    data = json.loads(result)
    assert "value" in data
    assert data["value"] > 0
    assert "condition" in data


def test_evaluate_damage_total_loss():
    from claim_agent.tools.logic import evaluate_damage_impl

    result = evaluate_damage_impl("Vehicle totaled in flood. Water damage throughout.", 15000)
    data = json.loads(result)
    assert data["total_loss_candidate"] is True
    assert data["severity"] == "high"


def test_generate_claim_id():
    from claim_agent.tools.logic import generate_claim_id_impl

    id1 = generate_claim_id_impl("CLM")
    id2 = generate_claim_id_impl("CLM")
    assert id1.startswith("CLM-")
    assert id2.startswith("CLM-")
    assert id1 != id2


def test_generate_report():
    from claim_agent.tools.logic import generate_report_impl

    result = generate_report_impl("CLM-ABC123", "new", "open", "Claim validated and assigned.", None)
    data = json.loads(result)
    assert data["claim_id"] == "CLM-ABC123"
    assert data["status"] == "open"
    assert data["summary"] == "Claim validated and assigned."
    assert "report_id" in data
