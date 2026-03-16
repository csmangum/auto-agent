"""Bodily injury workflow tools.

CrewAI tools for BI claims: query medical records, assess injury severity,
calculate settlement, PIP/MedPay exhaustion, CMS reporting, minor settlement,
structured settlement, loss of earnings, medical bill audit, treatment timeline.
"""

from __future__ import annotations

from crewai.tools import tool

from claim_agent.tools.bodily_injury_logic import (
    assess_injury_severity_impl,
    audit_medical_bills_impl,
    build_treatment_timeline_impl,
    calculate_bi_settlement_impl,
    calculate_loss_of_earnings_impl,
    check_cms_reporting_required_impl,
    check_minor_settlement_approval_impl,
    check_pip_medpay_exhaustion_impl,
    get_structured_settlement_option_impl,
    query_medical_records_impl,
)


@tool("Query Medical Records")
def query_medical_records(claim_id: str, claimant_id: str = "") -> str:
    """Query medical records associated with a bodily injury claim.

    Returns treatment summary, diagnoses, charges, and provider information.
    Use this to gather medical documentation before assessing severity.

    Args:
        claim_id: The claim ID to query records for.
        claimant_id: Optional claimant identifier (e.g., claimant-1).

    Returns:
        JSON with records, total_charges, treatment_summary.
    """
    return query_medical_records_impl(claim_id=claim_id, claimant_id=claimant_id)


@tool("Assess Injury Severity")
def assess_injury_severity(
    injury_description: str,
    medical_records_json: str = "",
) -> str:
    """Assess injury severity based on description and medical records.

    Classifies severity as minor, moderate, severe, or catastrophic and
    provides recommended settlement range. Use after gathering injury
    details and medical records.

    Args:
        injury_description: Description of injuries sustained.
        medical_records_json: Optional JSON from query_medical_records.

    Returns:
        JSON with severity, factors, recommended_range_low, recommended_range_high.
    """
    return assess_injury_severity_impl(
        injury_description=injury_description,
        medical_records_json=medical_records_json,
    )


@tool("Calculate BI Settlement")
def calculate_bi_settlement(
    claim_id: str,
    policy_number: str,
    medical_charges: float,
    injury_severity: str,
    pain_suffering_multiplier: float = 1.5,
) -> str:
    """Calculate proposed bodily injury settlement within policy limits.

    Combines medical specials with pain and suffering (multiplier method)
    and caps at policy BI limits. Use after reviewing medical records
    and assessing injury severity.

    Args:
        claim_id: The claim ID.
        policy_number: Policy number for limit lookup.
        medical_charges: Total medical expenses (specials).
        injury_severity: Severity from assess_injury_severity (minor/moderate/severe/catastrophic).
        pain_suffering_multiplier: Multiplier for pain/suffering (default 1.5).

    Returns:
        JSON with proposed_settlement, medical_charges, pain_suffering,
        policy_bi_limit_per_person, policy_bi_limit_per_accident.
    """
    return calculate_bi_settlement_impl(
        claim_id=claim_id,
        policy_number=policy_number,
        medical_charges=medical_charges,
        injury_severity=injury_severity,
        pain_suffering_multiplier=pain_suffering_multiplier,
    )


@tool("Check PIP/MedPay Exhaustion")
def check_pip_medpay_exhaustion(
    claim_id: str,
    policy_number: str,
    medical_charges: float,
    loss_state: str = "",
) -> str:
    """Check whether PIP/MedPay is exhausted before BI settlement.

    In no-fault states (FL, NY, etc.), BI settlement typically requires
    PIP/MedPay exhaustion. Use before proposing BI settlement.

    Args:
        claim_id: The claim ID.
        policy_number: Policy number for coverage lookup.
        medical_charges: Total medical charges (to compare with PIP limit).
        loss_state: State where loss occurred (e.g., FL, NY).

    Returns:
        JSON with has_pip_medpay, exhausted, bi_settlement_allowed.
    """
    return check_pip_medpay_exhaustion_impl(
        claim_id=claim_id,
        policy_number=policy_number,
        medical_charges=medical_charges,
        loss_state=loss_state,
    )


@tool("Check CMS Reporting Required")
def check_cms_reporting_required(
    claim_id: str,
    settlement_amount: float,
    claimant_medicare_eligible: bool = False,
) -> str:
    """Check whether CMS/Medicare reporting is required (MMSEA Section 111).

    Settlements >$750 involving Medicare beneficiaries require reporting.

    Args:
        claim_id: The claim ID.
        settlement_amount: Proposed settlement amount.
        claimant_medicare_eligible: Whether claimant is Medicare beneficiary.

    Returns:
        JSON with reporting_required, conditional_payment_amount, msa_required.
    """
    return check_cms_reporting_required_impl(
        claim_id=claim_id,
        settlement_amount=settlement_amount,
        claimant_medicare_eligible=claimant_medicare_eligible,
    )


@tool("Check Minor Settlement Approval")
def check_minor_settlement_approval(
    claim_id: str,
    claimant_age: int | None = None,
    claimant_incapacitated: bool = False,
    loss_state: str = "",
) -> str:
    """Check whether court approval is required for minor/incapacitated claimant.

    Many states require court approval for settlements involving minors.

    Args:
        claim_id: The claim ID.
        claimant_age: Claimant age (under 18 = minor).
        claimant_incapacitated: Whether claimant is legally incapacitated.
        loss_state: State jurisdiction.

    Returns:
        JSON with court_approval_required, court_approval_obtained.
    """
    return check_minor_settlement_approval_impl(
        claim_id=claim_id,
        claimant_age=claimant_age,
        claimant_incapacitated=claimant_incapacitated,
        loss_state=loss_state,
    )


@tool("Get Structured Settlement Option")
def get_structured_settlement_option(
    claim_id: str,
    total_settlement: float,
    lump_sum_pct: float = 0.3,
) -> str:
    """Generate structured settlement option for large BI claims.

    Periodic payments can provide tax advantages (IRC §104(a)(2)).

    Args:
        claim_id: The claim ID.
        total_settlement: Total settlement amount.
        lump_sum_pct: Fraction as lump sum (0-1); remainder as periodic.

    Returns:
        JSON with lump_sum_amount, periodic_payments, recommended.
    """
    return get_structured_settlement_option_impl(
        claim_id=claim_id,
        total_settlement=total_settlement,
        lump_sum_pct=lump_sum_pct,
    )


@tool("Calculate Loss of Earnings")
def calculate_loss_of_earnings(
    pre_accident_income: float,
    days_missed: int,
    income_type: str = "w2",
) -> str:
    """Calculate loss of earnings from wage and days missed.

    Args:
        pre_accident_income: Pre-accident annual or monthly income.
        days_missed: Work days missed due to injury.
        income_type: w2, 1099, or self_employed.

    Returns:
        JSON with recommended_amount, daily_rate, documentation_required.
    """
    return calculate_loss_of_earnings_impl(
        pre_accident_income=pre_accident_income,
        days_missed=days_missed,
        income_type=income_type,
    )


@tool("Audit Medical Bills")
def audit_medical_bills(
    medical_records_json: str,
    incident_date: str = "",
) -> str:
    """Audit medical bills for duplicates, excessive treatment, unrelated conditions.

    Args:
        medical_records_json: JSON from query_medical_records.
        incident_date: Incident date for timeline context.

    Returns:
        JSON with audit_findings, total_allowed, reduction_amount.
    """
    return audit_medical_bills_impl(
        medical_records_json=medical_records_json,
        incident_date=incident_date,
    )


@tool("Build Treatment Timeline")
def build_treatment_timeline(
    medical_records_json: str,
    incident_date: str = "",
) -> str:
    """Build treatment timeline from medical records for settlement valuation.

    Treatment duration affects settlement value.

    Args:
        medical_records_json: JSON from query_medical_records.
        incident_date: Incident date.

    Returns:
        JSON with treatment_duration_days, events, total_charges.
    """
    return build_treatment_timeline_impl(
        medical_records_json=medical_records_json,
        incident_date=incident_date,
    )
