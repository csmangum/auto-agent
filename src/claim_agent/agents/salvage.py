"""Agents for the salvage disposition workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.tools import (
    escalate_claim,
    generate_report,
    get_salvage_value,
    get_total_loss_requirements,
    initiate_title_transfer,
    record_dmv_salvage_report,
    record_salvage_disposition,
    search_policy_compliance,
    submit_nmvtis_report,
)
from claim_agent.skills import (
    AUCTION_LIAISON,
    SALVAGE_COORDINATOR,
    TITLE_SPECIALIST,
    load_skill,
    load_skill_with_context,
)


def create_salvage_coordinator_agent(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the salvage coordinator for total-loss vehicle disposition."""
    if use_rag:
        skill = load_skill_with_context(
            SALVAGE_COORDINATOR,
            state=state,
        )
    else:
        skill = load_skill(SALVAGE_COORDINATOR)

    tools = [get_salvage_value, generate_report, escalate_claim]
    if use_rag:
        tools.extend([get_total_loss_requirements, search_policy_compliance])

    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )


def create_title_specialist_agent(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the title specialist for salvage title transfer."""
    if use_rag:
        skill = load_skill_with_context(
            TITLE_SPECIALIST,
            state=state,
        )
    else:
        skill = load_skill(TITLE_SPECIALIST)

    tools = [
        initiate_title_transfer,
        record_dmv_salvage_report,
        submit_nmvtis_report,
        generate_report,
        escalate_claim,
    ]
    if use_rag:
        tools.extend([get_total_loss_requirements, search_policy_compliance])

    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )


def create_auction_liaison_agent(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the auction liaison for tracking salvage disposition."""
    if use_rag:
        skill = load_skill_with_context(
            AUCTION_LIAISON,
            state=state,
        )
    else:
        skill = load_skill(AUCTION_LIAISON)

    tools = [record_salvage_disposition, submit_nmvtis_report, generate_report, escalate_claim]
    if use_rag:
        tools.extend([get_total_loss_requirements, search_policy_compliance])

    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )
