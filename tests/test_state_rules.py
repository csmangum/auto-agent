"""Tests for state-specific compliance rules engine."""

from claim_agent.compliance.state_rules import (
    get_state_rules,
    get_total_loss_threshold,
    get_prompt_payment_days,
    get_compliance_due_date,
    get_siu_referral_threshold,
    get_comparative_fault_rules,
    is_recovery_eligible,
)
from datetime import date


class TestGetStateRules:
    def test_california_rules(self):
        rules = get_state_rules("California")
        assert rules is not None
        assert rules.state == "California"
        assert rules.prompt_payment_days == 30
        assert rules.total_loss_threshold == 0.75

    def test_florida_rules(self):
        rules = get_state_rules("Florida")
        assert rules is not None
        assert rules.prompt_payment_days == 90
        assert rules.total_loss_threshold == 0.80

    def test_texas_rules(self):
        rules = get_state_rules("Texas")
        assert rules is not None
        assert rules.total_loss_threshold == 0.80

    def test_new_york_rules(self):
        rules = get_state_rules("New York")
        assert rules is not None
        assert rules.prompt_payment_days == 30

    def test_normalizes_case(self):
        rules = get_state_rules("california")
        assert rules is not None
        assert rules.state == "California"

    def test_unsupported_state_returns_none(self):
        assert get_state_rules("Invalid") is None

    def test_empty_returns_none(self):
        assert get_state_rules("") is None
        assert get_state_rules(None) is None

    def test_georgia_diminished_value_formula(self):
        rules = get_state_rules("Georgia")
        assert rules is not None
        assert rules.diminished_value_required is True
        assert rules.diminished_value_formula == "ga_17c"


class TestGetTotalLossThreshold:
    def test_california_75_percent(self):
        assert get_total_loss_threshold("California") == 0.75

    def test_florida_80_percent(self):
        assert get_total_loss_threshold("Florida") == 0.80

    def test_unknown_defaults_to_75(self):
        assert get_total_loss_threshold(None) == 0.75


class TestGetPromptPaymentDays:
    def test_california_30_days(self):
        assert get_prompt_payment_days("California") == 30

    def test_florida_90_days(self):
        assert get_prompt_payment_days("Florida") == 90

    def test_unknown_defaults_to_30(self):
        assert get_prompt_payment_days(None) == 30


class TestGetComplianceDueDate:
    def test_acknowledgment(self):
        base = date(2025, 1, 15)
        due = get_compliance_due_date(base, "acknowledgment", "California")
        assert due == date(2025, 1, 30)

    def test_prompt_payment(self):
        base = date(2025, 1, 1)
        due = get_compliance_due_date(base, "prompt_payment", "Florida")
        assert due == date(2025, 4, 1)

    def test_investigation(self):
        base = date(2025, 1, 1)
        due = get_compliance_due_date(base, "investigation", "California")
        assert due == date(2025, 2, 10)

    def test_unknown_deadline_type_returns_none(self):
        assert get_compliance_due_date(date(2025, 1, 1), "unknown", "California") is None


class TestGetSiuReferralThreshold:
    def test_california_has_threshold(self):
        assert get_siu_referral_threshold("California") == 75

    def test_unknown_returns_none(self):
        assert get_siu_referral_threshold("Invalid") is None


class TestGetComparativeFaultRules:
    def test_california_pure_comparative(self):
        rules = get_comparative_fault_rules("California")
        assert rules["comparative_fault_type"] == "pure_comparative"
        assert rules["comparative_fault_bar"] is None
        assert rules["state"] == "California"

    def test_texas_modified_51(self):
        rules = get_comparative_fault_rules("Texas")
        assert rules["comparative_fault_type"] == "modified_comparative_51"
        assert rules["comparative_fault_bar"] == 51.0

    def test_florida_modified_51(self):
        rules = get_comparative_fault_rules("Florida")
        assert rules["comparative_fault_type"] == "modified_comparative_51"
        assert rules["comparative_fault_bar"] == 51.0

    def test_unknown_defaults_pure(self):
        rules = get_comparative_fault_rules("Invalid")
        assert rules["comparative_fault_type"] == "pure_comparative"
        assert rules["state"] is None

    def test_georgia_modified_51(self):
        rules = get_comparative_fault_rules("Georgia")
        assert rules["comparative_fault_type"] == "modified_comparative_51"
        assert rules["comparative_fault_bar"] == 51.0
        assert rules["state"] == "Georgia"

    def test_abbreviation_ca_resolves(self):
        rules = get_comparative_fault_rules("CA")
        assert rules is not None
        assert rules["state"] == "California"


class TestIsRecoveryEligible:
    def test_pure_comparative_always_eligible(self):
        assert is_recovery_eligible(0.0, "California") is True
        assert is_recovery_eligible(99.0, "California") is True
        assert is_recovery_eligible(None, "California") is True

    def test_modified_51_bar(self):
        assert is_recovery_eligible(0.0, "Texas") is True
        assert is_recovery_eligible(50.0, "Texas") is True
        assert is_recovery_eligible(51.0, "Texas") is False
        assert is_recovery_eligible(60.0, "Texas") is False

    def test_unknown_state_eligible(self):
        assert is_recovery_eligible(50.0, None) is True

    def test_georgia_51_bar(self):
        assert is_recovery_eligible(0.0, "Georgia") is True
        assert is_recovery_eligible(50.0, "Georgia") is True
        assert is_recovery_eligible(51.0, "Georgia") is False
