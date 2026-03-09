"""Denial and coverage dispute logic: letter generation and appeal routing."""

import json
from datetime import datetime


def generate_denial_letter_impl(
    claim_id: str,
    denial_reason: str,
    policy_provision: str,
    exclusion_citation: str | None = None,
    appeal_deadline: str | None = None,
    required_disclosures: str | None = None,
) -> str:
    """Generate a formatted denial letter."""
    lines = [
        "=" * 60,
        "CLAIM DENIAL NOTICE",
        "=" * 60,
        "",
        f"Claim ID: {claim_id}",
        f"Date: {datetime.utcnow().strftime('%Y-%m-%d')}",
        "",
        "Dear Policyholder,",
        "",
        "We have completed our review of your claim. After careful consideration of the policy "
        "terms and the circumstances of your claim, we must deny coverage for the following reason:",
        "",
        f"DENIAL REASON: {denial_reason}",
        "",
        f"APPLICABLE POLICY PROVISION: {policy_provision}",
    ]
    if exclusion_citation:
        lines.extend(["", f"EXCLUSION: {exclusion_citation}", ""])
    if appeal_deadline:
        lines.extend([
            "",
            "APPEAL RIGHTS:",
            f"You have the right to appeal this decision. Your appeal must be received by {appeal_deadline}.",
            "",
        ])
    if required_disclosures:
        lines.extend(["", "REQUIRED NOTICES:", required_disclosures, ""])
    lines.extend([
        "If you have questions or wish to provide additional information, please contact us.",
        "",
        "Sincerely,",
        "Claims Department",
        "=" * 60,
    ])
    return "\n".join(lines)


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
        "routed_at": datetime.utcnow().isoformat(),
    }
    if policyholder_evidence:
        result["policyholder_evidence"] = policyholder_evidence
    if recommended_action:
        result["recommended_action"] = recommended_action
    return json.dumps(result, indent=2)
