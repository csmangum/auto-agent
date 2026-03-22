"""Denial and coverage dispute logic: letter generation and appeal routing."""

import json
from datetime import datetime, timezone


def generate_denial_letter_impl(
    claim_id: str,
    denial_reason: str,
    policy_provision: str,
    exclusion_citation: str | None = None,
    appeal_deadline: str | None = None,
    required_disclosures: str | None = None,
    state: str | None = None,
) -> str:
    """Generate a formatted denial letter.

    When *state* is provided and a matching template exists the letter uses
    state-specific wording, regulatory references, and mandated disclosures
    (e.g. California CCR §2695.7(g), Texas TIC §542.056).  Falls back to the
    generic format when no template is available for the given state.
    """
    from claim_agent.compliance.denial_templates import render_denial_letter

    return render_denial_letter(
        claim_id=claim_id,
        denial_reason=denial_reason,
        policy_provision=policy_provision,
        state=state,
        exclusion_citation=exclusion_citation,
        appeal_deadline=appeal_deadline,
        required_disclosures=required_disclosures,
    )


def route_to_appeal_impl(
    claim_id: str,
    appeal_reason: str,
    policyholder_evidence: str | None = None,
    recommended_action: str | None = None,
) -> str:
    """Record appeal routing. Returns confirmation JSON.

    Note: The actual status update is performed by the orchestrator.
    This tool returns a structured confirmation for the crew output.
    """
    result = {
        "claim_id": claim_id,
        "routed_to_appeal": True,
        "appeal_reason": appeal_reason,
        "routed_at": datetime.now(timezone.utc).isoformat(),
    }
    if policyholder_evidence:
        result["policyholder_evidence"] = policyholder_evidence
    if recommended_action:
        result["recommended_action"] = recommended_action
    return json.dumps(result, indent=2)
