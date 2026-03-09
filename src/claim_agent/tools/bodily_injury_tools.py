"""Bodily injury workflow tools.

CrewAI tools for BI claims: query medical records, assess injury severity,
calculate settlement.
"""

from __future__ import annotations

from crewai.tools import tool

from claim_agent.tools.bodily_injury_logic import (
    assess_injury_severity_impl,
    calculate_bi_settlement_impl,
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
