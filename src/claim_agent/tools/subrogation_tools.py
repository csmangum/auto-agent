"""Subrogation tools: assess liability, build case, send demand, record recovery."""

from typing import Union

from crewai.tools import tool

from claim_agent.tools.subrogation_logic import (
    assess_liability_impl,
    build_subrogation_case_impl,
    record_arbitration_filing_impl,
    record_recovery_impl,
    send_demand_letter_impl,
)


@tool("Assess Liability")
def assess_liability(
    incident_description: str,
    claim_data: str = "",
    workflow_output: str = "",
) -> str:
    """Evaluate incident description and claim context to determine fault.

    Determines whether the insured was at-fault or not-at-fault, and identifies
    third-party involvement when applicable. Use for subrogation eligibility.

    Args:
        incident_description: Description of how the accident occurred.
        claim_data: Optional JSON string of claim data.
        workflow_output: Optional workflow and settlement output for context.

    Returns:
        JSON with is_not_at_fault, fault_determination, third_party_identified, reasoning.
    """
    return assess_liability_impl(
        incident_description=incident_description,
        claim_data_json=claim_data or "",
        workflow_output=workflow_output or "",
    )


@tool("Build Subrogation Case")
def build_subrogation_case(
    claim_id: str,
    payout_amount: float,
    liability_assessment: str,
    claim_data: str = "",
) -> str:
    """Build a subrogation recovery case from liability assessment and payout.

    Creates the case file with amount sought, third-party info, and supporting docs.

    Args:
        claim_id: The claim ID.
        payout_amount: Amount paid to the policyholder (amount to recover).
        liability_assessment: JSON output from assess_liability.
        claim_data: Optional JSON string of claim data.

    Returns:
        JSON with case_id, amount_sought, third_party_info, supporting_docs.
    """
    return build_subrogation_case_impl(
        claim_id=claim_id,
        payout_amount=payout_amount,
        liability_assessment=liability_assessment,
        claim_data_json=claim_data or "",
    )


@tool("Send Demand Letter")
def send_demand_letter(
    case_id: str,
    claim_id: str,
    amount_sought: float,
    third_party_info: str = "",
) -> str:
    """Generate and send demand letter to at-fault party (or their insurer).

    Args:
        case_id: Subrogation case ID.
        claim_id: Claim ID.
        amount_sought: Amount being demanded.
        third_party_info: Optional notes about the third party.

    Returns:
        JSON with confirmation, letter_id, sent_at.
    """
    return send_demand_letter_impl(
        case_id=case_id,
        claim_id=claim_id,
        amount_sought=amount_sought,
        third_party_info=third_party_info or "",
    )


@tool("Record Arbitration Filing")
def record_arbitration_filing(
    case_id: str,
    arbitration_forum: str = "Arbitration Forums Inc.",
    dispute_date: str = "",
) -> str:
    """Record that a subrogation dispute has been filed for inter-company arbitration.

    Use when the opposing carrier disputes liability and the case is filed with
    an arbitration forum (e.g., Arbitration Forums Inc.).

    Args:
        case_id: Subrogation case ID.
        arbitration_forum: Forum name (default: Arbitration Forums Inc.).
        dispute_date: Date dispute was filed (YYYY-MM-DD). Defaults to today.

    Returns:
        JSON with confirmation.
    """
    return record_arbitration_filing_impl(
        case_id=case_id,
        arbitration_forum=arbitration_forum,
        dispute_date=dispute_date,
    )


@tool("Record Recovery")
def record_recovery(
    claim_id: str,
    case_id: str,
    recovery_amount: Union[float, None] = None,
    recovery_status: str = "pending",
    notes: str = "",
) -> str:
    """Record recovery amount and status for subrogation tracking.

    Args:
        claim_id: The claim ID.
        case_id: Subrogation case ID.
        recovery_amount: Amount recovered (if any).
        recovery_status: pending, partial, full, or closed_no_recovery.
        notes: Optional notes about recovery status.

    Returns:
        JSON with recorded recovery details.
    """
    return record_recovery_impl(
        claim_id=claim_id,
        case_id=case_id,
        recovery_amount=recovery_amount,
        recovery_status=recovery_status,
        notes=notes or "",
    )
