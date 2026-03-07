"""Escalation (HITL) tools: evaluate escalation, detect fraud indicators, generate report."""

import json

from crewai.tools import tool

from claim_agent.exceptions import MidWorkflowEscalation
from claim_agent.tools.logic import (
    detect_fraud_indicators_impl,
    escalate_claim_impl,
    evaluate_escalation_impl,
)


@tool("Evaluate Escalation")
def evaluate_escalation(
    claim_data: str,
    router_output: str,
    similarity_score: str = "",
    payout_amount: str = "",
) -> str:
    """Evaluate whether a claim needs human review based on low confidence, high value, ambiguous similarity, or fraud indicators.
    Args:
        claim_data: JSON string of claim input (policy_number, vin, vehicle_year, vehicle_make, vehicle_model, incident_date, incident_description, damage_description, estimated_damage).
        router_output: Raw text output from the router classification.
        similarity_score: Optional numeric string (0-100) for duplicate similarity.
        payout_amount: Optional numeric string for payout/settlement amount.
    Returns:
        JSON with needs_review (bool), escalation_reasons (list), priority (str), fraud_indicators (list), recommended_action (str).
    """
    data = {}
    if isinstance(claim_data, str) and claim_data.strip():
        try:
            data = json.loads(claim_data)
        except json.JSONDecodeError:
            data = {}
    sim = None
    if similarity_score and str(similarity_score).strip():
        try:
            sim = float(similarity_score)
        except (ValueError, TypeError):
            # Invalid similarity score; leave sim as None and treat as no similarity provided.
            pass
    payout = None
    if payout_amount and str(payout_amount).strip():
        try:
            payout = float(payout_amount)
        except (ValueError, TypeError):
            # Invalid payout amount; leave payout as None and treat as no payout provided.
            pass
    return evaluate_escalation_impl(data, router_output or "", sim, payout)


@tool("Escalate Claim")
def escalate_claim(
    claim_data: str,
    reason: str,
    indicators: str = "[]",
    priority: str = "medium",
) -> str:
    """Escalate a claim for human review mid-workflow. Halts crew execution immediately.

    Use when you discover fraud, high risk, or inconsistencies during processing
    (e.g., damage inconsistent with incident description, liability dispute).

    Args:
        claim_data: JSON string of claim input. Must include claim_id.
        reason: Escalation reason (e.g., 'damage_inconsistent_with_incident', 'fraud_indicators').
        indicators: JSON array of fraud/risk indicator strings (optional).
        priority: low, medium, high, or critical.

    Raises:
        MidWorkflowEscalation: Always. Execution halts; claim is routed to review queue.
    """
    data = {}
    if isinstance(claim_data, str) and claim_data.strip():
        try:
            data = json.loads(claim_data)
        except json.JSONDecodeError:
            data = {}
    claim_id = data.get("claim_id") if isinstance(data, dict) else None
    if not claim_id:
        raise ValueError("claim_data must include claim_id for escalate_claim")
    claim_id = str(claim_id).strip()
    claim_type = data.get("claim_type") if isinstance(data, dict) else None
    claim_type = str(claim_type).strip() if claim_type else None

    ind_list = []
    if indicators and str(indicators).strip():
        try:
            parsed = json.loads(indicators)
            ind_list = list(parsed) if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            ind_list = []

    normalized_reason = reason.strip() or "mid_workflow_escalation"
    normalized_priority = priority.strip() or "medium"

    escalate_claim_impl(
        claim_id=claim_id,
        reason=normalized_reason,
        indicators=ind_list,
        priority=normalized_priority,
        claim_type=claim_type,
    )
    raise MidWorkflowEscalation(
        reason=normalized_reason,
        indicators=ind_list,
        priority=normalized_priority,
        claim_id=claim_id,
    )


@tool("Detect Fraud Indicators")
def detect_fraud_indicators(claim_data: str) -> str:
    """Check claim data for fraud indicators (staged accident keywords, multiple claims same VIN, damage vs value, description mismatch).
    Args:
        claim_data: JSON string of claim input.
    Returns:
        JSON array of fraud indicator strings.
    """
    data = {}
    if isinstance(claim_data, str) and claim_data.strip():
        try:
            data = json.loads(claim_data)
        except json.JSONDecodeError:
            data = {}
    return detect_fraud_indicators_impl(data)


@tool("Generate Escalation Report")
def generate_escalation_report(
    claim_id: str,
    needs_review: str,
    escalation_reasons: str,
    priority: str,
    recommended_action: str,
    fraud_indicators: str = "[]",
) -> str:
    """Format an escalation result as a human-readable report.
    Args:
        claim_id: Claim ID.
        needs_review: 'true' or 'false'.
        escalation_reasons: JSON array of reason strings.
        priority: low, medium, high, or critical.
        recommended_action: Recommended action text.
        fraud_indicators: JSON array of fraud indicator strings.
    Returns:
        Formatted report string.
    """
    try:
        reasons = json.loads(escalation_reasons) if escalation_reasons else []
    except json.JSONDecodeError:
        reasons = []
    try:
        indicators = json.loads(fraud_indicators) if fraud_indicators else []
    except json.JSONDecodeError:
        indicators = []
    is_review = str(needs_review).strip().lower() in ("true", "1", "yes")
    lines = [
        f"Escalation Report — Claim {claim_id}",
        f"Needs review: {is_review}",
        f"Priority: {priority}",
        f"Reasons: {', '.join(reasons) or 'None'}",
        f"Recommended action: {recommended_action}",
    ]
    if indicators:
        lines.append(f"Fraud indicators: {', '.join(indicators)}")
    return "\n".join(lines)
