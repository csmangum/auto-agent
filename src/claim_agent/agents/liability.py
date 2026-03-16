"""Agent for the liability determination workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.tools import (
    assess_liability,
    escalate_claim,
    search_state_compliance,
)
from claim_agent.tools.compliance_tools import get_comparative_fault_rules_tool
from claim_agent.skills import LIABILITY_ANALYST, load_skill, load_skill_with_context


def create_liability_analyst_agent(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the liability analyst agent for pre-settlement liability determination."""
    if use_rag:
        skill = load_skill_with_context(
            LIABILITY_ANALYST,
            state=state,
        )
    else:
        skill = load_skill(LIABILITY_ANALYST)

    tools = [
        assess_liability,
        search_state_compliance,
        get_comparative_fault_rules_tool,
        escalate_claim,
    ]

    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )
