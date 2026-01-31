"""Unit tests for claim tools."""

import json
import os
import tempfile
from pathlib import Path

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
    """Search uses SQLite; seed a claim in a temp DB then search."""
    from claim_agent.db.database import init_db
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput
    from claim_agent.tools.logic import search_claims_db_impl

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        repo = ClaimRepository(db_path=path)
        repo.create_claim(
            ClaimInput(
                policy_number="POL-001",
                vin="1HGBH41JXMN109186",
                vehicle_year=2021,
                vehicle_make="Honda",
                vehicle_model="Accord",
                incident_date="2025-01-15",
                incident_description="Rear-ended at stoplight. Damage to rear bumper and trunk.",
                damage_description="Rear bumper and trunk.",
            )
        )
        result = search_claims_db_impl("1HGBH41JXMN109186", "2025-01-15")
        claims = json.loads(result)
        assert isinstance(claims, list)
        assert len(claims) >= 1
        assert claims[0]["vin"] == "1HGBH41JXMN109186"
        assert claims[0]["claim_id"]
        assert claims[0]["incident_date"] == "2025-01-15"
    finally:
        os.unlink(path)
        os.environ.pop("CLAIMS_DB_PATH", None)


def test_search_claims_db_empty():
    """Search with no matches returns [] using a temp DB to avoid test pollution."""
    from claim_agent.db.database import init_db
    from claim_agent.tools.logic import search_claims_db_impl

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        result = search_claims_db_impl("UNKNOWN_VIN_XYZ", "2020-01-01")
        claims = json.loads(result)
        assert claims == []
    finally:
        os.unlink(path)
        os.environ.pop("CLAIMS_DB_PATH", None)


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


def test_compute_similarity_symmetric():
    """Jaccard similarity is symmetric: sim(a, b) == sim(b, a)."""
    from claim_agent.tools.logic import compute_similarity_impl

    a = "Rear-ended at stoplight. Damage to rear bumper."
    b = "Damage to rear bumper and trunk. Rear-ended."
    result_ab = json.loads(compute_similarity_impl(a, b))
    result_ba = json.loads(compute_similarity_impl(b, a))
    assert result_ab["similarity_score"] == result_ba["similarity_score"]
    assert result_ab["is_duplicate"] == result_ba["is_duplicate"]


def test_compute_similarity_empty_strings():
    from claim_agent.tools.logic import compute_similarity_impl

    result = json.loads(compute_similarity_impl("", "something"))
    assert result["similarity_score"] == 0.0
    assert result["is_duplicate"] is False

    result2 = json.loads(compute_similarity_impl("  ", "other"))
    assert result2["similarity_score"] == 0.0


def test_query_policy_db_invalid_input():
    from claim_agent.tools.logic import query_policy_db_impl

    result = json.loads(query_policy_db_impl(""))
    assert result["valid"] is False
    assert "message" in result

    result2 = json.loads(query_policy_db_impl("   "))
    assert result2["valid"] is False


def test_query_policy_db_inactive_returns_invalid():
    """Inactive policy (e.g. POL-021) must return valid False."""
    from claim_agent.tools.logic import query_policy_db_impl

    result = query_policy_db_impl("POL-021")
    data = json.loads(result)
    assert data["valid"] is False
    assert data.get("status") == "inactive"


def test_mock_db_claim_vins_have_vehicle_values():
    """Every claim VIN in mock_db must exist in vehicle_values (regression guard)."""
    from claim_agent.tools.data_loader import load_mock_db

    db = load_mock_db()
    claims = db.get("claims", [])
    vehicle_values = db.get("vehicle_values", {})
    missing = []
    for c in claims:
        vin = c.get("vin")
        if vin and vin not in vehicle_values:
            missing.append(vin)
    assert not missing, f"Claims reference VINs not in vehicle_values: {missing}"


def test_search_claims_db_empty_vin_returns_empty():
    from claim_agent.tools.logic import search_claims_db_impl

    result = search_claims_db_impl("", "2025-01-15")
    assert json.loads(result) == []

    result2 = search_claims_db_impl("VIN123", "")
    assert json.loads(result2) == []


def test_evaluate_damage_empty_description():
    from claim_agent.tools.logic import evaluate_damage_impl

    result = json.loads(evaluate_damage_impl("", 1000))
    assert result["severity"] == "unknown"
    assert result["total_loss_candidate"] is False
    assert result["estimated_repair_cost"] == 1000


def test_search_california_compliance_empty_returns_summary():
    from claim_agent.tools.logic import search_california_compliance_impl

    result = search_california_compliance_impl("")
    data = json.loads(result)
    assert "sections" in data
    assert "metadata" in data
    assert "fair_claims_settlement_practices" in data["sections"]


def test_search_california_compliance_query_returns_matches():
    from claim_agent.tools.logic import search_california_compliance_impl

    result = search_california_compliance_impl("total loss")
    data = json.loads(result)
    assert "matches" in data
    assert data["match_count"] >= 1
    assert data["query"] == "total loss"


def test_search_california_compliance_ccr_reference():
    from claim_agent.tools.logic import search_california_compliance_impl

    result = search_california_compliance_impl("2695.5")
    data = json.loads(result)
    assert "matches" in data
    assert data["match_count"] >= 1


def test_search_california_compliance_missing_file_returns_error():
    from claim_agent.tools.logic import search_california_compliance_impl

    os.environ["CA_COMPLIANCE_PATH"] = "/nonexistent/california_auto_compliance.json"
    try:
        result = search_california_compliance_impl("deadline")
        data = json.loads(result)
        assert "error" in data
        assert data["matches"] == []
    finally:
        os.environ.pop("CA_COMPLIANCE_PATH", None)
