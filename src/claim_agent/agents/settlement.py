"""Agents for the shared settlement workflow."""

from crewai import Agent

from claim_agent.tools import (
    calculate_payout,
    escalate_claim,
    generate_claim_id,
    generate_report,
    get_compliance_deadlines,
    search_policy_compliance,
)
from claim_agent.skills import (
    PAYMENT_DISTRIBUTION,
    SETTLEMENT_CLOSURE,
    SETTLEMENT_DOCUMENTATION,
    load_skill,
    load_skill_with_context,
)


def create_settlement_documentation_agent(
    llm=None,
    state: str = "California",
    claim_type: str | None = None,
    use_rag: bool = True,
):
    """Create the documentation specialist for shared settlement."""
    if use_rag:
        skill = load_skill_with_context(
            SETTLEMENT_DOCUMENTATION,
            state=state,
            claim_type=claim_type,
        )
    else:
        skill = load_skill(SETTLEMENT_DOCUMENTATION)

    tools = [generate_report, generate_claim_id, escalate_claim]
    if use_rag:
        tools.extend([get_compliance_deadlines, search_policy_compliance])

    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )


def create_payment_distribution_agent(
    llm=None,
    state: str = "California",
    claim_type: str | None = None,
    use_rag: bool = True,
):
    """Create the payment distribution specialist for shared settlement."""
    if use_rag:
        skill = load_skill_with_context(
            PAYMENT_DISTRIBUTION,
            state=state,
            claim_type=claim_type,
        )
    else:
        skill = load_skill(PAYMENT_DISTRIBUTION)

    tools = [calculate_payout, generate_report, escalate_claim]
    if use_rag:
        tools.extend([get_compliance_deadlines, search_policy_compliance])

    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )


def create_settlement_closure_agent(
    llm=None,
    state: str = "California",
    claim_type: str | None = None,
    use_rag: bool = True,
):
    """Create the closure specialist for shared settlement."""
    if use_rag:
        skill = load_skill_with_context(
            SETTLEMENT_CLOSURE,
            state=state,
            claim_type=claim_type,
        )
    else:
        skill = load_skill(SETTLEMENT_CLOSURE)

    tools = [generate_report, generate_claim_id, escalate_claim]
    if use_rag:
        tools.extend([get_compliance_deadlines, search_policy_compliance])

    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )
