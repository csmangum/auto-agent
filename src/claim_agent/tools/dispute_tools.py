"""Dispute handling tools: claim lookup, classification, and report generation."""

import json
from typing import Union

from crewai.tools import tool

from claim_agent.tools.dispute_logic import (
    classify_dispute_impl,
    generate_dispute_report_impl,
    lookup_original_claim_impl,
)


@tool("Lookup Original Claim")
def lookup_original_claim(claim_id: str) -> str:
    """Retrieve original claim record, workflow result, and settlement details for a disputed claim.

    Args:
        claim_id: The ID of the claim being disputed.

    Returns:
        JSON with claim data, workflow outputs, and payout information.
    """
    return lookup_original_claim_impl(claim_id)


@tool("Classify Dispute")
def classify_dispute(
    claim_data: str,
    dispute_description: str,
    dispute_type_hint: str = "",
) -> str:
    """Classify a policyholder dispute and determine if it can be auto-resolved.

    Args:
        claim_data: JSON string of claim data.
        dispute_description: Policyholder's description of the dispute.
        dispute_type_hint: Optional pre-classified dispute type.

    Returns:
        JSON with dispute_type, auto_resolvable, original_amounts, policyholder_position.
    """
    data = {}
    if isinstance(claim_data, str) and claim_data.strip():
        try:
            data = json.loads(claim_data)
        except json.JSONDecodeError:
            data = {}

    return classify_dispute_impl(
        data,
        dispute_description,
        dispute_type_hint if dispute_type_hint else None,
    )


@tool("Generate Dispute Report")
def generate_dispute_report(
    claim_id: str,
    dispute_type: str,
    resolution_type: str,
    findings: str,
    original_amount: str = "",
    adjusted_amount: str = "",
    escalation_reasons: Union[str, list] = "",
    recommended_action: str = "",
    compliance_notes: Union[str, list] = "",
    policyholder_rights: Union[str, list] = "",
) -> str:
    """Generate a formatted dispute resolution report.

    Args:
        claim_id: The claim ID.
        dispute_type: Type of dispute (valuation_disagreement, repair_estimate, etc.).
        resolution_type: 'auto_resolved' or 'escalated'.
        findings: Analysis findings text.
        original_amount: Original payout/estimate amount as string.
        adjusted_amount: Adjusted amount as string (empty if unchanged).
        escalation_reasons: JSON array or list of escalation reason strings.
        recommended_action: Recommended next steps.
        compliance_notes: JSON array or list of compliance note strings.
        policyholder_rights: JSON array or list of policyholder rights strings.

    Returns:
        Formatted dispute resolution report.
    """
    esc_reasons = _parse_list(escalation_reasons)
    comp_notes = _parse_list(compliance_notes)
    ph_rights = _parse_list(policyholder_rights)

    return generate_dispute_report_impl(
        claim_id=claim_id,
        dispute_type=dispute_type,
        resolution_type=resolution_type,
        findings=findings,
        original_amount=original_amount or None,
        adjusted_amount=adjusted_amount or None,
        escalation_reasons=esc_reasons,
        recommended_action=recommended_action,
        compliance_notes=comp_notes,
        policyholder_rights=ph_rights,
    )


def _parse_list(value: Union[str, list]) -> list[str]:
    if isinstance(value, list):
        return value
    if not value or not str(value).strip():
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return [value]
