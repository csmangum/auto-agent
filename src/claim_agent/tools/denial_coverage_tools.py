"""Denial and coverage dispute tools: denial letter generation and appeal routing.

When invoked by the denial/coverage crew, these tools use the process-default
database. The orchestrator uses the injected ctx.repo for writes.
"""

from crewai.tools import tool

from claim_agent.tools.denial_coverage_logic import (
    generate_denial_letter_impl,
    route_to_appeal_impl,
)


@tool("Generate Denial Letter")
def generate_denial_letter(
    claim_id: str,
    denial_reason: str,
    policy_provision: str,
    exclusion_citation: str = "",
    appeal_deadline: str = "",
    required_disclosures: str = "",
) -> str:
    """Generate a compliant denial letter for a denied claim.

    Args:
        claim_id: The claim ID.
        denial_reason: Clear, specific reason for the denial.
        policy_provision: Policy provision or exclusion that applies.
        exclusion_citation: Optional specific exclusion language.
        appeal_deadline: Deadline for policyholder to appeal.
        required_disclosures: State-mandated disclosures to include.

    Returns:
        Formatted denial letter text.
    """
    return generate_denial_letter_impl(
        claim_id=claim_id,
        denial_reason=denial_reason,
        policy_provision=policy_provision,
        exclusion_citation=exclusion_citation or None,
        appeal_deadline=appeal_deadline or None,
        required_disclosures=required_disclosures or None,
    )


@tool("Route to Appeal")
def route_to_appeal(
    claim_id: str,
    appeal_reason: str,
    policyholder_evidence: str = "",
    recommended_action: str = "",
) -> str:
    """Route a denied claim to appeal when denial is not well-supported or new evidence warrants reconsideration.

    Args:
        claim_id: The claim ID.
        appeal_reason: Reason for routing to appeal (e.g., exclusion not clearly applicable).
        policyholder_evidence: Optional evidence provided by policyholder.
        recommended_action: Recommended next steps for appeal processor.

    Returns:
        Confirmation of appeal routing with claim_id and appeal_reason.
    """
    return route_to_appeal_impl(
        claim_id=claim_id,
        appeal_reason=appeal_reason,
        policyholder_evidence=policyholder_evidence or None,
        recommended_action=recommended_action or None,
    )
