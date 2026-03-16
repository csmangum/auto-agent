"""Compliance tools: California lookup and state-specific deadlines."""

import json
from datetime import date

from crewai.tools import tool

from claim_agent.compliance.state_rules import (
    get_state_rules,
    get_compliance_due_date,
    get_comparative_fault_rules,
)
from claim_agent.rag.constants import SUPPORTED_STATES, normalize_state
from claim_agent.tools.compliance_logic import (
    search_california_compliance_impl,
    search_state_compliance_impl,
)


@tool("Search State Auto Compliance")
def search_state_compliance(query: str = "", state: str = "California") -> str:
    """Search state auto insurance compliance/regulatory reference data by keyword.

    Use for claims handling rules, deadlines, disclosures, and related regulations.
    Pass state=loss_state from claim_data for multi-state claims.
    Pass an empty string for query to get a section summary.

    Args:
        query: Search term (e.g. 'total loss', 'deadline', 'disclosure'). Optional.
        state: State jurisdiction - California, Texas, Florida, New York, or Georgia.

    Returns:
        JSON with match_count and matches (or section summary if query is empty).
    """
    return search_state_compliance_impl(query, state)


@tool("Search California Auto Compliance")
def search_california_compliance(query: str = "") -> str:
    """Search California auto insurance compliance/regulatory reference data by keyword.
    Use for claims handling rules, deadlines, disclosures, CCR/CIC references, and related regulations.
    Pass an empty string to get a section summary.
    Args:
        query: Search term (e.g. 'total loss', '2695.5', 'disclosure', 'deadline'). Optional.
    Returns:
        JSON with match_count and matches (or section summary if query is empty).
    """
    return search_california_compliance_impl(query)


@tool("Get State Compliance Summary")
def get_state_compliance_summary(state: str) -> str:
    """Get state-specific compliance rules and deadlines for claim processing.

    Use this when creating compliance-related tasks (e.g., acknowledgment,
    investigation, prompt payment) to set correct due dates per state.

    Args:
        state: State jurisdiction - California, Texas, Florida, New York, or Georgia.

    Returns:
        JSON with acknowledgment_days, investigation_days, prompt_payment_days,
        total_loss_threshold, siu_referral_threshold, diminished_value_required.
    """
    if not isinstance(state, str) or not state.strip():
        return json.dumps({
            "error": f"Invalid or missing state. Supported: {', '.join(SUPPORTED_STATES)}.",
            "state": None,
        })
    try:
        normalized = normalize_state(state.strip())
    except ValueError:
        return json.dumps({
            "error": f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}.",
            "state": None,
        })
    rules = get_state_rules(normalized)
    if not rules:
        return json.dumps({
            "error": f"No rules found for {normalized}.",
            "state": normalized,
        })
    return json.dumps({
        "state": rules.state,
        "acknowledgment_days": rules.acknowledgment_days,
        "investigation_days": rules.investigation_days,
        "prompt_payment_days": rules.prompt_payment_days,
        "total_loss_threshold": rules.total_loss_threshold,
        "siu_referral_threshold": rules.siu_referral_threshold,
        "diminished_value_required": rules.diminished_value_required,
        "appraisal_rights": rules.appraisal_rights,
    })


@tool("Get Comparative Fault Rules")
def get_comparative_fault_rules_tool(state: str = "California") -> str:
    """Get state-specific comparative fault rules for liability determination.

    Use when determining liability and subrogation eligibility. Rules vary by state:
    - pure_comparative (CA, NY): recovery reduced by fault %; no bar
    - modified_comparative_51 (TX, FL): no recovery if insured >= 51% at fault
    - contributory: no recovery if insured has any fault

    Args:
        state: State jurisdiction - California, Texas, Florida, New York, or Georgia.

    Returns:
        JSON with comparative_fault_type, comparative_fault_bar, state.
    """
    rules = get_comparative_fault_rules(state)
    return json.dumps(rules)


@tool("Get Compliance Due Date")
def get_compliance_due_date_tool(
    base_date: str,
    deadline_type: str,
    state: str,
) -> str:
    """Compute the due date for a compliance deadline.

    Use when creating claim_tasks for compliance obligations (acknowledgment,
    investigation, prompt_payment) to set state-specific due dates.

    Args:
        base_date: Reference date in YYYY-MM-DD (e.g., claim receipt, acceptance).
        deadline_type: One of: acknowledgment, investigation, prompt_payment.
        state: State jurisdiction - California, Texas, Florida, New York, or Georgia.

    Returns:
        JSON with due_date (YYYY-MM-DD) and days.
    """
    if not isinstance(state, str) or not state.strip():
        return json.dumps({
            "error": "State is required and must be a non-empty string.",
            "due_date": None,
        })
    try:
        normalized = normalize_state(state.strip())
    except ValueError:
        return json.dumps({
            "error": f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}.",
            "due_date": None,
        })
    if not isinstance(base_date, str) or not base_date.strip():
        return json.dumps({
            "error": "base_date is required and must be a non-empty string in YYYY-MM-DD format.",
            "due_date": None,
        })
    try:
        base = date.fromisoformat(base_date.strip())
    except ValueError:
        return json.dumps({
            "error": "Invalid base_date. Use YYYY-MM-DD format.",
            "due_date": None,
        })
    due = get_compliance_due_date(base, deadline_type, normalized)
    if not due:
        return json.dumps({
            "error": f"Unknown deadline_type: {deadline_type}. Use: acknowledgment, investigation, prompt_payment.",
            "due_date": None,
        })
    rules = get_state_rules(normalized)
    if rules is None:
        return json.dumps({
            "error": f"No compliance rules found for state: {normalized}.",
            "due_date": None,
        })
    days = (
        rules.acknowledgment_days
        if deadline_type == "acknowledgment"
        else rules.investigation_days
        if deadline_type == "investigation"
        else rules.prompt_payment_days
        if deadline_type == "prompt_payment"
        else 0
    )
    return json.dumps({
        "due_date": due.isoformat(),
        "days": days,
        "deadline_type": deadline_type,
        "state": normalized,
    })
