"""Unit tests for claim tools."""

import json
import os
import tempfile
from pathlib import Path

import pytest

# Point to project data for mock_db
os.environ.setdefault(
    "MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json")
)


def test_query_policy_db_found():
    from claim_agent.models.policy_lookup import PolicyLookupSuccess
    from claim_agent.tools.policy_logic import query_policy_db_impl

    result = query_policy_db_impl("POL-001")
    assert isinstance(result, PolicyLookupSuccess)
    assert result.valid is True
    assert result.coverage
    assert result.deductible == 500
    assert result.effective_date == "2020-01-01"
    assert result.expiration_date == "2030-12-31"


def test_coerce_policy_date_str_normalizes_iso_datetime_strings():
    from claim_agent.tools.policy_logic import _coerce_policy_date_str

    assert _coerce_policy_date_str("2023-06-01T14:30:00") == "2023-06-01"
    assert _coerce_policy_date_str("2023-06-01T14:30:00Z") == "2023-06-01"
    assert _coerce_policy_date_str("  ") is None


def test_query_policy_db_term_alias_normalized():
    """term_start/term_end from adapter are exposed as effective_date/expiration_date."""
    from claim_agent.models.policy_lookup import PolicyLookupSuccess
    from claim_agent.tools.policy_logic import query_policy_db_impl

    result = query_policy_db_impl("POL-TERM-ALIAS")
    assert isinstance(result, PolicyLookupSuccess)
    assert result.effective_date == "2023-06-01"
    assert result.expiration_date == "2026-06-01"
    dumped = result.model_dump()
    assert "term_start" not in dumped


def test_query_policy_db_masks_full_name_and_display_name():
    """Named insured / drivers from mock_db may use full_name or display_name; output uses name only."""
    from claim_agent.models.policy_lookup import PolicyLookupSuccess
    from claim_agent.tools.policy_logic import query_policy_db_impl

    result = query_policy_db_impl("POL-FULLNAME-TEST")
    assert isinstance(result, PolicyLookupSuccess)
    assert result.named_insured == [{"name": "Alex Alternate"}]
    assert result.drivers == [{"name": "Alex Alternate", "relationship": "primary"}]
    dumped = result.model_dump_json()
    assert "email" not in dumped
    assert "full_name" not in dumped
    assert "display_name" not in dumped


def test_query_policy_db_not_found():
    from claim_agent.models.policy_lookup import PolicyLookupFailure
    from claim_agent.tools.policy_logic import query_policy_db_impl

    result = query_policy_db_impl("POL-999")
    assert isinstance(result, PolicyLookupFailure)
    assert result.valid is False


def test_search_claims_db():
    """Search uses SQLite; seed a claim in a temp DB then search."""
    from claim_agent.config import reload_settings
    from claim_agent.db.database import init_db
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput
    from claim_agent.tools.claims_logic import search_claims_db_impl

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        reload_settings()
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
    from claim_agent.tools.claims_logic import search_claims_db_impl

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


def test_add_claim_note_and_get_claim_notes(temp_db):
    """add_claim_note and get_claim_notes tools work with a temp DB."""
    from claim_agent.db.repository import ClaimRepository
    from claim_agent.models.claim import ClaimInput
    from claim_agent.tools.claim_notes_tools import add_claim_note, get_claim_notes

    repo = ClaimRepository()
    claim_id = repo.create_claim(
        ClaimInput(
            policy_number="POL-001",
            vin="VIN123",
            vehicle_year=2021,
            vehicle_make="Honda",
            vehicle_model="Accord",
            incident_date="2025-01-15",
            incident_description="Test",
            damage_description="Test",
        )
    )

    result = get_claim_notes.run(claim_id=claim_id)
    data = json.loads(result)
    assert data["notes"] == []
    assert data["error"] is None

    result = add_claim_note.run(
        claim_id=claim_id,
        note="New Claim: Policy verified.",
        actor_id="New Claim",
    )
    data = json.loads(result)
    assert data["success"] is True

    result = get_claim_notes.run(claim_id=claim_id)
    data = json.loads(result)
    assert data["error"] is None
    notes = data["notes"]
    assert len(notes) == 1
    assert notes[0]["note"] == "New Claim: Policy verified."
    assert notes[0]["actor_id"] == "New Claim"
    assert notes[0].get("created_at") is not None


def test_add_claim_note_nonexistent_returns_error(temp_db):
    """add_claim_note returns success=False for nonexistent claim."""
    from claim_agent.tools.claim_notes_tools import add_claim_note

    result = add_claim_note.run(
        claim_id="CLM-NONEXIST",
        note="Test",
        actor_id="workflow",
    )
    data = json.loads(result)
    assert data["success"] is False
    assert "Claim not found" in data["message"]


def test_get_claim_notes_nonexistent_returns_error(temp_db):
    """get_claim_notes returns error format for nonexistent claim."""
    from claim_agent.tools.claim_notes_tools import get_claim_notes

    result = get_claim_notes.run(claim_id="CLM-NONEXIST")
    data = json.loads(result)
    assert data["notes"] is None
    assert "Claim not found" in data["error"]


def test_compute_similarity_high():
    from claim_agent.tools.claims_logic import compute_similarity_impl

    a = "Rear-ended at stoplight. Damage to rear bumper and trunk."
    b = "Rear-ended at stoplight. Damage to rear bumper and trunk."
    result = json.loads(compute_similarity_impl(a, b))
    assert result["similarity_score"] >= 80
    assert result["is_duplicate"] is True


def test_compute_similarity_low():
    from claim_agent.tools.claims_logic import compute_similarity_impl

    a = "Parking lot scratch."
    b = "Total loss flood damage."
    result = json.loads(compute_similarity_impl(a, b))
    assert result["similarity_score"] < 80
    assert result["is_duplicate"] is False


def test_fetch_vehicle_value():
    from claim_agent.tools.valuation_logic import fetch_vehicle_value_impl

    result = fetch_vehicle_value_impl("1HGBH41JXMN109186", 2021, "Honda", "Accord")
    data = json.loads(result)
    assert "value" in data
    assert data["value"] > 0
    assert "condition" in data


def test_evaluate_damage_total_loss():
    from claim_agent.tools.valuation_logic import evaluate_damage_impl

    result = evaluate_damage_impl("Vehicle totaled in flood. Water damage throughout.", 15000)
    data = json.loads(result)
    assert data["total_loss_candidate"] is True
    assert data["severity"] == "high"


def test_generate_claim_id():
    from claim_agent.tools.document_logic import generate_claim_id_impl

    id1 = generate_claim_id_impl("CLM")
    id2 = generate_claim_id_impl("CLM")
    assert id1.startswith("CLM-")
    assert id2.startswith("CLM-")
    assert id1 != id2


def test_generate_report():
    from claim_agent.tools.document_logic import generate_report_impl

    result = generate_report_impl(
        "CLM-ABC123", "new", "open", "Claim validated and assigned.", None
    )
    data = json.loads(result)
    assert data["claim_id"] == "CLM-ABC123"
    assert data["status"] == "open"
    assert data["summary"] == "Claim validated and assigned."
    assert "report_id" in data


def test_compute_similarity_symmetric():
    """Similarity is symmetric: sim(a, b) == sim(b, a)."""
    from claim_agent.tools.claims_logic import compute_similarity_impl

    a = "Rear-ended at stoplight. Damage to rear bumper."
    b = "Damage to rear bumper and trunk. Rear-ended."
    result_ab = json.loads(compute_similarity_impl(a, b))
    result_ba = json.loads(compute_similarity_impl(b, a))
    assert result_ab["similarity_score"] == result_ba["similarity_score"]
    assert result_ab["is_duplicate"] == result_ba["is_duplicate"]


def test_compute_similarity_empty_strings():
    from claim_agent.tools.claims_logic import compute_similarity_impl

    result = json.loads(compute_similarity_impl("", "something"))
    assert result["similarity_score"] == 0.0
    assert result["is_duplicate"] is False

    result2 = json.loads(compute_similarity_impl("  ", "other"))
    assert result2["similarity_score"] == 0.0


def test_query_policy_db_invalid_input():
    from claim_agent.exceptions import DomainValidationError
    from claim_agent.tools.policy_logic import query_policy_db_impl

    with pytest.raises(DomainValidationError):
        query_policy_db_impl("")
    with pytest.raises(DomainValidationError):
        query_policy_db_impl("   ")


def test_query_policy_db_impl_validation_error_maps_to_adapter_error(monkeypatch):
    """Pydantic validation failures become AdapterError so MCP/CrewAI tools return JSON errors."""
    from pydantic import ValidationError

    from claim_agent.exceptions import AdapterError
    from claim_agent.tools import policy_logic as policy_logic_mod

    def boom(data: dict) -> None:
        raise ValidationError.from_exception_data(
            "PolicyLookupResult",
            [{"type": "missing", "loc": ("coverage",), "input": data}],
        )

    monkeypatch.setattr(policy_logic_mod, "policy_lookup_from_dict", boom)

    with pytest.raises(AdapterError, match="invalid data"):
        policy_logic_mod.query_policy_db_impl("POL-001")


def test_query_policy_db_inactive_returns_invalid():
    """Inactive policy (e.g. POL-021) must return valid False."""
    from claim_agent.models.policy_lookup import PolicyLookupFailure
    from claim_agent.tools.policy_logic import query_policy_db_impl

    result = query_policy_db_impl("POL-021")
    assert isinstance(result, PolicyLookupFailure)
    assert result.status == "inactive"


def test_mock_db_claim_vins_have_vehicle_values():
    """Every claim VIN in mock_db must exist in vehicle_values (regression guard)."""
    from claim_agent.data.loader import load_mock_db

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
    from claim_agent.tools.claims_logic import search_claims_db_impl

    result = search_claims_db_impl("", "2025-01-15")
    assert json.loads(result) == []

    result2 = search_claims_db_impl("VIN123", "")
    assert json.loads(result2) == []


def test_evaluate_damage_empty_description():
    from claim_agent.tools.valuation_logic import evaluate_damage_impl

    result = json.loads(evaluate_damage_impl("", 1000))
    assert result["severity"] == "unknown"
    assert result["total_loss_candidate"] is False
    assert result["estimated_repair_cost"] == 1000


def test_search_california_compliance_empty_returns_summary():
    from claim_agent.tools.compliance_logic import search_california_compliance_impl

    result = search_california_compliance_impl("")
    data = json.loads(result)
    assert "sections" in data
    assert "metadata" in data
    assert "fair_claims_settlement_practices" in data["sections"]


def test_search_california_compliance_query_returns_matches():
    from claim_agent.tools.compliance_logic import search_california_compliance_impl

    result = search_california_compliance_impl("total loss")
    data = json.loads(result)
    assert "matches" in data
    assert data["match_count"] >= 1
    assert data["query"] == "total loss"


def test_search_california_compliance_ccr_reference():
    from claim_agent.tools.compliance_logic import search_california_compliance_impl

    result = search_california_compliance_impl("2695.5")
    data = json.loads(result)
    assert "matches" in data
    assert data["match_count"] >= 1


def test_search_california_compliance_missing_file_returns_error():
    from claim_agent.config import reload_settings
    from claim_agent.tools.compliance_logic import (
        _search_state_compliance_cached,
        search_california_compliance_impl,
    )

    _search_state_compliance_cached.cache_clear()
    os.environ["CA_COMPLIANCE_PATH"] = "/nonexistent/california_auto_compliance.json"
    reload_settings()
    try:
        result = search_california_compliance_impl("deadline")
        data = json.loads(result)
        assert "error" in data
        assert data["matches"] == []
    finally:
        os.environ.pop("CA_COMPLIANCE_PATH", None)


def test_search_state_compliance_texas():
    from claim_agent.tools.compliance_logic import search_state_compliance_impl

    result = search_state_compliance_impl("total loss", "Texas")
    data = json.loads(result)
    assert "matches" in data
    assert data["match_count"] >= 1
    assert data["query"] == "total loss"


def test_search_state_compliance_invalid_state_returns_error():
    from claim_agent.tools.compliance_logic import search_state_compliance_impl

    result = search_state_compliance_impl("deadline", "InvalidState")
    data = json.loads(result)
    assert "error" in data
    assert "match_count" in data
    assert data["match_count"] == 0


def test_calculate_payout_valid_policy():
    """Test payout calculation with valid policy."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    result = calculate_payout_impl(12000, "POL-001")
    data = json.loads(result)
    assert "payout_amount" in data
    assert data["payout_amount"] == 11500.0  # 12000 - 500 (POL-001 deductible)
    assert data["vehicle_value"] == 12000
    assert data["deductible"] == 500
    assert "calculation" in data


def test_calculate_payout_high_deductible():
    """Test payout calculation with high deductible policy."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    result = calculate_payout_impl(12000, "POL-012")
    data = json.loads(result)
    assert data["payout_amount"] == 10000.0  # 12000 - 2000 (POL-012 deductible)
    assert data["deductible"] == 2000


def test_calculate_payout_invalid_policy():
    """Test payout calculation with invalid policy returns error."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    result = calculate_payout_impl(12000, "POL-999")
    data = json.loads(result)
    assert "error" in data
    assert data["payout_amount"] == 0.0


def test_calculate_payout_zero_vehicle_value():
    """Test payout calculation with zero vehicle value."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    result = calculate_payout_impl(0, "POL-001")
    data = json.loads(result)
    assert "error" in data
    assert data["payout_amount"] == 0.0


def test_calculate_payout_negative_vehicle_value():
    """Test payout calculation with negative vehicle value."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    result = calculate_payout_impl(-1000, "POL-001")
    data = json.loads(result)
    assert "error" in data
    assert data["payout_amount"] == 0.0


def test_calculate_payout_deductible_exceeds_value():
    """Test payout calculation where deductible exceeds vehicle value."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    result = calculate_payout_impl(1000, "POL-012")
    data = json.loads(result)
    # POL-012 has 2000 deductible, vehicle value 1000, payout should be 0
    assert data["payout_amount"] == 0.0
    assert data["deductible"] == 2000


def test_calculate_payout_liability_only_policy_returns_error():
    """Liability-only policy should not produce first-party physical damage payout."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    result = calculate_payout_impl(12000, "POL-002")
    data = json.loads(result)
    assert "error" in data
    assert data["payout_amount"] == 0.0


def test_calculate_payout_requires_context_for_asymmetric_deductibles():
    """Policies with different collision/comprehensive deductibles require context."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    result = calculate_payout_impl(12000, "POL-099")
    data = json.loads(result)
    assert "error" in data
    assert data["payout_amount"] == 0.0


def test_calculate_payout_uses_explicit_coverage_type():
    """Coverage type should select the matching deductible for payout."""
    from claim_agent.tools.valuation_logic import calculate_payout_impl

    collision_result = calculate_payout_impl(12000, "POL-099", coverage_type="collision")
    comprehensive_result = calculate_payout_impl(12000, "POL-099", coverage_type="comprehensive")
    collision_data = json.loads(collision_result)
    comprehensive_data = json.loads(comprehensive_result)

    assert collision_data["payout_amount"] == 11750.0
    assert collision_data["deductible"] == 250.0
    assert comprehensive_data["payout_amount"] == 11000.0
    assert comprehensive_data["deductible"] == 1000.0
