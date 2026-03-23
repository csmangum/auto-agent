"""Tests for claim_agent.tools.payment_logic helpers."""

from claim_agent.tools.payment_logic import (
    WORKFLOW_RENTAL_EXTERNAL_REF_PREFIX,
    is_workflow_rental_external_ref,
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
