"""LiabilityDeterminationOutput tolerates LLM omissions (fault_determination)."""

from claim_agent.models.claim import LiabilityDeterminationOutput


def test_fills_fault_determination_when_missing_from_liability_pct():
    m = LiabilityDeterminationOutput.model_validate(
        {
            "liability_percentage": 30.0,
            "liability_basis": "Comparative fault",
            "third_party_identified": True,
            "recovery_eligible": True,
        }
    )
    assert m.fault_determination == "at_fault"


def test_missing_fault_zero_pct_is_not_at_fault():
    m = LiabilityDeterminationOutput.model_validate(
        {
            "liability_percentage": 0.0,
            "liability_basis": "Other party solely liable",
        }
    )
    assert m.fault_determination == "not_at_fault"


def test_missing_fault_no_pct_is_unclear():
    m = LiabilityDeterminationOutput.model_validate(
        {
            "liability_basis": "Insufficient facts",
        }
    )
    assert m.fault_determination == "unclear"


def test_blank_fault_determination_string_is_inferred():
    m = LiabilityDeterminationOutput.model_validate(
        {
            "liability_percentage": 100.0,
            "liability_basis": "x",
            "fault_determination": "   ",
        }
    )
    assert m.fault_determination == "at_fault"


def test_explicit_fault_determination_preserved():
    m = LiabilityDeterminationOutput.model_validate(
        {
            "liability_percentage": 0.0,
            "fault_determination": "unclear",
        }
    )
    assert m.fault_determination == "unclear"


def test_malformed_llm_payload_with_unrelated_fields_still_parses():
    """gpt-4o-mini sometimes returns claim-ish keys instead of liability schema."""
    m = LiabilityDeterminationOutput.model_validate(
        {
            "incident_description": "Rear-ended at light",
            "estimated_repair_days": 5,
        }
    )
    assert m.fault_determination == "unclear"
    assert m.liability_percentage is None
