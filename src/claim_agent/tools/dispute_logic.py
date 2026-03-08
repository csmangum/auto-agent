"""Dispute handling logic: claim lookup, dispute classification, and report generation."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from claim_agent.db.repository import ClaimRepository
from claim_agent.models.dispute import AUTO_RESOLVABLE_DISPUTE_TYPES, DisputeType

if TYPE_CHECKING:
    from claim_agent.context import ClaimContext

logger = logging.getLogger(__name__)

_DISPUTE_KEYWORDS: dict[str, list[str]] = {
    DisputeType.VALUATION_DISAGREEMENT.value: [
        "acv", "actual cash value", "valuation", "comparable",
        "market value", "undervalued", "vehicle worth", "appraisal",
    ],
    DisputeType.REPAIR_ESTIMATE.value: [
        "oem", "aftermarket", "parts", "labor rate", "repair cost",
        "shop estimate", "repair estimate", "original equipment",
    ],
    DisputeType.DEDUCTIBLE_APPLICATION.value: [
        "deductible", "prior damage", "deductible waiver",
        "wrong deductible", "deductible amount",
    ],
    DisputeType.LIABILITY_DETERMINATION.value: [
        "liability", "fault", "other driver", "witness",
        "police report", "brake-checked", "not at fault", "disputed liability",
    ],
}


def lookup_original_claim_impl(
    claim_id: str,
    *,
    ctx: ClaimContext | None = None,
) -> str:
    """Retrieve original claim record, workflow result, and settlement details.

    When ctx is None (e.g. when invoked by the crew with only tool args),
    uses the process-default ClaimRepository. Crew-invoked tools do not
    receive request-scoped context.

    Returns JSON with claim data, workflow output, and payout information.
    """
    repo = ctx.repo if ctx else ClaimRepository()

    claim = repo.get_claim(claim_id)
    if claim is None:
        return json.dumps({"error": f"Claim not found: {claim_id}"})

    workflow_runs = repo.get_workflow_runs(claim_id)

    result = {
        "claim_id": claim_id,
        "claim": {
            "status": claim.get("status"),
            "claim_type": claim.get("claim_type"),
            "policy_number": claim.get("policy_number"),
            "vin": claim.get("vin"),
            "vehicle_year": claim.get("vehicle_year"),
            "vehicle_make": claim.get("vehicle_make"),
            "vehicle_model": claim.get("vehicle_model"),
            "incident_date": claim.get("incident_date"),
            "incident_description": claim.get("incident_description"),
            "damage_description": claim.get("damage_description"),
            "estimated_damage": claim.get("estimated_damage"),
            "payout_amount": claim.get("payout_amount"),
        },
        "workflow_runs": workflow_runs,
    }
    return json.dumps(result)


def classify_dispute_impl(
    claim_data: dict[str, Any],
    dispute_description: str,
    dispute_type_hint: str | None = None,
) -> str:
    """Classify a dispute and determine auto-resolvability.

    If *dispute_type_hint* is provided and valid, it takes precedence.
    Otherwise the dispute is classified by keyword matching on the description.
    """
    if dispute_type_hint:
        try:
            dtype = DisputeType(dispute_type_hint)
        except ValueError:
            dtype = _classify_by_keywords(dispute_description)
    else:
        dtype = _classify_by_keywords(dispute_description)

    auto_resolvable = dtype in AUTO_RESOLVABLE_DISPUTE_TYPES

    result = {
        "dispute_type": dtype.value,
        "auto_resolvable": auto_resolvable,
        "original_amounts": {
            "payout_amount": claim_data.get("payout_amount"),
            "estimated_damage": claim_data.get("estimated_damage"),
        },
        "policyholder_position": dispute_description,
    }
    return json.dumps(result)


def _classify_by_keywords(description: str) -> DisputeType:
    """Score dispute description against keyword lists and return best match."""
    lower = description.lower()
    scores: dict[str, int] = {}
    for dtype_val, keywords in _DISPUTE_KEYWORDS.items():
        scores[dtype_val] = sum(1 for kw in keywords if kw in lower)

    best = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best] == 0:
        return DisputeType.LIABILITY_DETERMINATION
    return DisputeType(best)


def generate_dispute_report_impl(
    claim_id: str,
    dispute_type: str,
    resolution_type: str,
    findings: str,
    original_amount: str | None = None,
    adjusted_amount: str | None = None,
    escalation_reasons: list[str] | None = None,
    recommended_action: str = "",
    compliance_notes: list[str] | None = None,
    policyholder_rights: list[str] | None = None,
) -> str:
    """Generate a formatted dispute resolution report."""
    escalation_reasons = escalation_reasons or []
    compliance_notes = compliance_notes or []
    policyholder_rights = policyholder_rights or []

    orig_display = _format_amount(original_amount)
    adj_display = _format_amount(adjusted_amount)

    lines = [
        "=" * 60,
        f"DISPUTE RESOLUTION REPORT — Claim {claim_id}",
        "=" * 60,
        "",
        f"Dispute Type: {dispute_type.replace('_', ' ').title()}",
        f"Resolution: {resolution_type.upper().replace('_', ' ')}",
        "",
    ]

    if orig_display:
        lines.append(f"Original Amount: {orig_display}")
    if adj_display:
        lines.append(f"Adjusted Amount: {adj_display}")
    if orig_display or adj_display:
        lines.append("")

    lines.extend(["Findings:", f"  {findings}", ""])

    if escalation_reasons:
        lines.append("Escalation Reasons:")
        for i, reason in enumerate(escalation_reasons, 1):
            lines.append(f"  {i}. {reason}")
        lines.append("")

    if recommended_action:
        lines.extend(["Recommended Action:", f"  {recommended_action}", ""])

    if compliance_notes:
        lines.append("Compliance Notes:")
        for note in compliance_notes:
            lines.append(f"  - {note}")
        lines.append("")

    if policyholder_rights:
        lines.append("Policyholder Rights:")
        for right in policyholder_rights:
            lines.append(f"  - {right}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def _format_amount(value: str | float | None) -> str | None:
    if value is None:
        return None
    try:
        return f"${float(value):,.2f}"
    except (ValueError, TypeError):
        return str(value) if value else None
