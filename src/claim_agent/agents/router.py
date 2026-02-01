"""Router / Manager agent for claim classification and delegation."""

from crewai import Agent

from claim_agent.skills import load_skill, ROUTER


def create_router_agent(llm=None):
    """Create the Claim Router Supervisor agent (manager in hierarchical process)."""
    skill = load_skill(ROUTER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        allow_delegation=True,
        verbose=True,
        llm=llm,
    )
