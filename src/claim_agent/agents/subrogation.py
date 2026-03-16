"""Agents for the subrogation recovery workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.tools import (
    assess_liability,
    build_subrogation_case,
    escalate_claim,
    generate_report,
    get_compliance_deadlines,
    record_arbitration_filing,
    record_recovery,
    search_policy_compliance,
    send_demand_letter,
)
from claim_agent.skills import (
    DEMAND_SPECIALIST,
    LIABILITY_INVESTIGATOR,
    RECOVERY_TRACKER,
    load_skill,
    load_skill_with_context,
)


def create_liability_investigator_agent(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the liability investigator for subrogation."""
    if use_rag:
        skill = load_skill_with_context(
            LIABILITY_INVESTIGATOR,
            state=state,
        )
    else:
        skill = load_skill(LIABILITY_INVESTIGATOR)

    tools = [assess_liability, escalate_claim]
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


def create_demand_specialist_agent(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the demand specialist for subrogation."""
    if use_rag:
        skill = load_skill_with_context(
            DEMAND_SPECIALIST,
            state=state,
        )
    else:
        skill = load_skill(DEMAND_SPECIALIST)

    tools = [build_subrogation_case, send_demand_letter, generate_report, escalate_claim]
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


def create_recovery_tracker_agent(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the recovery tracker for subrogation."""
    if use_rag:
        skill = load_skill_with_context(
            RECOVERY_TRACKER,
            state=state,
        )
    else:
        skill = load_skill(RECOVERY_TRACKER)

    tools = [record_recovery, record_arbitration_filing, generate_report, escalate_claim]
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
