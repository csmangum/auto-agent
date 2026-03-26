"""Tests for state-specific compliance rules engine."""

from claim_agent.compliance.state_rules import (
    get_state_rules,
    get_total_loss_threshold,
    get_prompt_payment_days,
    get_compliance_due_date,
    get_siu_referral_threshold,
    get_comparative_fault_rules,
    get_nicb_deadline_days,
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

    def test_california_nicb_theft_deadline(self):
        """CA has a strict 5-working-day (≈7 calendar day) NICB theft deadline."""
        rules = get_state_rules("California")
        assert rules is not None
        assert rules.nicb_deadline_days_theft == 7

    def test_california_nicb_salvage_deadline(self):
        rules = get_state_rules("California")
        assert rules is not None
        assert rules.nicb_deadline_days_salvage == 30

    def test_new_jersey_nicb_theft_deadline(self):
        """NJ has a strict 2-working-day (≈3 calendar day) NICB theft deadline."""
        rules = get_state_rules("New Jersey")
        assert rules is not None
        assert rules.nicb_deadline_days_theft == 3

    def test_pennsylvania_rules(self):
        rules = get_state_rules("Pennsylvania")
        assert rules is not None
        assert rules.state == "Pennsylvania"
        assert rules.prompt_payment_days == 30
        assert rules.total_loss_threshold == 0.75
        assert rules.acknowledgment_days == 14
        assert rules.investigation_days == 30
        assert rules.comparative_fault_type == "modified_comparative_51"
        assert rules.comparative_fault_bar == 51.0

    def test_illinois_rules(self):
        rules = get_state_rules("Illinois")
        assert rules is not None
        assert rules.state == "Illinois"
        assert rules.prompt_payment_days == 30
        assert rules.total_loss_threshold == 0.80
        assert rules.acknowledgment_days == 14
        assert rules.investigation_days == 45
        assert rules.communication_response_days == 14
        assert rules.comparative_fault_type == "modified_comparative_51"
        assert rules.comparative_fault_bar == 51.0

    def test_pennsylvania_abbreviation(self):
        rules = get_state_rules("PA")
        assert rules is not None
        assert rules.state == "Pennsylvania"

    def test_illinois_abbreviation(self):
        rules = get_state_rules("IL")
        assert rules is not None
        assert rules.state == "Illinois"


class TestGetTotalLossThreshold:
    def test_california_75_percent(self):
        assert get_total_loss_threshold("California") == 0.75

    def test_florida_80_percent(self):
        assert get_total_loss_threshold("Florida") == 0.80

    def test_unknown_defaults_to_75(self):
        assert get_total_loss_threshold(None) == 0.75

    def test_unsupported_state_string_uses_settings_fallback(self):
        """Unknown jurisdiction: same threshold path as missing state (settings default)."""
        assert get_total_loss_threshold("Alaska") == get_total_loss_threshold(None)

    def test_pennsylvania_75_percent(self):
        assert get_total_loss_threshold("Pennsylvania") == 0.75

    def test_illinois_80_percent(self):
        assert get_total_loss_threshold("Illinois") == 0.80


class TestGetPromptPaymentDays:
    def test_california_30_days(self):
        assert get_prompt_payment_days("California") == 30

    def test_florida_90_days(self):
        assert get_prompt_payment_days("Florida") == 90

    def test_unknown_defaults_to_30(self):
        assert get_prompt_payment_days(None) == 30

    def test_pennsylvania_30_days(self):
        assert get_prompt_payment_days("Pennsylvania") == 30

    def test_illinois_30_days(self):
        assert get_prompt_payment_days("Illinois") == 30


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

    def test_communication_response(self):
        base = date(2025, 1, 1)
        due = get_compliance_due_date(base, "communication_response", "California")
        assert due == date(2025, 1, 16)

    def test_communication_response_unknown_state_default(self):
        base = date(2025, 6, 1)
        due = get_compliance_due_date(base, "communication_response", "Nope")
        assert due == date(2025, 6, 16)


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
        assert rules["comparative_fault_bar"] == 50.0
        assert rules["state"] == "Georgia"

    def test_abbreviation_ca_resolves(self):
        rules = get_comparative_fault_rules("CA")
        assert rules is not None
        assert rules["state"] == "California"

    def test_pennsylvania_modified_51(self):
        rules = get_comparative_fault_rules("Pennsylvania")
        assert rules["comparative_fault_type"] == "modified_comparative_51"
        assert rules["comparative_fault_bar"] == 51.0
        assert rules["state"] == "Pennsylvania"

    def test_illinois_modified_51(self):
        rules = get_comparative_fault_rules("Illinois")
        assert rules["comparative_fault_type"] == "modified_comparative_51"
        assert rules["comparative_fault_bar"] == 51.0
        assert rules["state"] == "Illinois"


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
        assert is_recovery_eligible(49.0, "Georgia") is True
        assert is_recovery_eligible(50.0, "Georgia") is False
        assert is_recovery_eligible(51.0, "Georgia") is False


class TestGetNicbDeadlineDays:
    def test_california_theft_is_7_days(self):
        """CA vehicle theft must be filed with NICB within 5 working days (≈7 calendar days)."""
        assert get_nicb_deadline_days("California", "theft") == 7

    def test_california_salvage_is_30_days(self):
        assert get_nicb_deadline_days("California", "salvage") == 30

    def test_new_jersey_theft_is_3_days(self):
        """NJ vehicle theft must be filed with NICB within 2 working days (≈3 calendar days)."""
        assert get_nicb_deadline_days("New Jersey", "theft") == 3

    def test_new_jersey_abbreviation(self):
        assert get_nicb_deadline_days("NJ", "theft") == 3

    def test_florida_theft_defaults_30(self):
        assert get_nicb_deadline_days("Florida", "theft") == 30

    def test_texas_theft_defaults_30(self):
        assert get_nicb_deadline_days("Texas", "theft") == 30

    def test_unknown_state_defaults_30(self):
        assert get_nicb_deadline_days(None, "theft") == 30
        assert get_nicb_deadline_days("InvalidState", "theft") == 30

    def test_default_report_type_is_theft(self):
        """Omitting report_type should behave as theft."""
        assert get_nicb_deadline_days("California") == get_nicb_deadline_days("California", "theft")

    def test_salvage_type_falls_back_to_30_when_not_set(self):
        """States without explicit salvage rules fall back to 30 days."""
        for state in ("Florida", "Texas", "New York", "Georgia", "Pennsylvania", "Illinois"):
            assert get_nicb_deadline_days(state, "salvage") == 30
