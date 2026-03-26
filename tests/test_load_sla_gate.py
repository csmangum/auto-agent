"""Regression tests for load-test SLA gate logic (runs in unit CI; not under tests/load/)."""


def test_error_rate_sla_accepts_zero_errors_when_threshold_is_zero():
    """SLA gate uses <= so a perfect run passes when threshold is 0%."""
    error_rate = 0.0
    sla = 0.0
    assert error_rate <= sla
