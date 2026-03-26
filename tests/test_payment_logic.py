"""Tests for claim_agent.tools.payment_logic helpers."""

import json

from claim_agent.tools.payment_logic import (
    WORKFLOW_RENTAL_EXTERNAL_REF_PREFIX,
    is_workflow_rental_external_ref,
    record_claim_payment_impl,
)


def test_workflow_rental_prefix_constant():
    assert WORKFLOW_RENTAL_EXTERNAL_REF_PREFIX == "workflow_rental:"


def test_is_workflow_rental_external_ref_positive():
    assert is_workflow_rental_external_ref("workflow_rental:CLM-1")
    assert is_workflow_rental_external_ref("  WORKFLOW_RENTAL:run1  ")


def test_is_workflow_rental_external_ref_negative():
    assert not is_workflow_rental_external_ref(None)
    assert not is_workflow_rental_external_ref("")
    assert not is_workflow_rental_external_ref("other_prefix:rental")


def test_record_claim_payment_impl_invalid_payee_type():
    raw = record_claim_payment_impl(
        "CLM-X",
        1.0,
        "Payee",
        "not_a_payee_type",
        "ach",
    )
    data = json.loads(raw)
    assert data["success"] is False
    assert "payee_type" in data["hint"]


def test_record_claim_payment_impl_non_positive_amount():
    raw = record_claim_payment_impl(
        "CLM-X",
        0.0,
        "Payee",
        "claimant",
        "check",
    )
    assert json.loads(raw)["success"] is False


def test_record_claim_payment_impl_empty_payee():
    raw = record_claim_payment_impl(
        "CLM-X",
        10.0,
        "   ",
        "claimant",
        "ach",
    )
    assert json.loads(raw)["success"] is False


def test_record_claim_payment_impl_invalid_secondary_payee_type(monkeypatch, seeded_temp_db):
    monkeypatch.setattr("claim_agent.tools.payment_logic.get_db_path", lambda: seeded_temp_db)
    raw = record_claim_payment_impl(
        "CLM-TEST001",
        50.0,
        "Valid Payee",
        "claimant",
        "ach",
        payee_secondary="Other",
        payee_secondary_type="bogus_type",
    )
    data = json.loads(raw)
    assert data["success"] is False
    assert "payee_secondary_type" in data["error"]


def test_record_claim_payment_impl_claim_not_found(monkeypatch, seeded_temp_db):
    monkeypatch.setattr("claim_agent.tools.payment_logic.get_db_path", lambda: seeded_temp_db)
    raw = record_claim_payment_impl(
        "CLM-DOES-NOT-EXIST",
        25.0,
        "Payee",
        "claimant",
        "wire",
    )
    data = json.loads(raw)
    assert data["success"] is False
    assert "not found" in data["error"].lower()
