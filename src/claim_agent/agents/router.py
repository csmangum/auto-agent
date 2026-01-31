"""Router / Manager agent for claim classification and delegation."""

from crewai import Agent


def create_router_agent(llm=None):
    """Create the Claim Router Supervisor agent (manager in hierarchical process)."""
    return Agent(
        role="Claim Router Supervisor",
        goal="Classify the claim as 'new', 'duplicate', or 'total_loss' based on the claim description and data. If unclear, ask for more info. Then delegate to the appropriate workflow.",
        backstory="Senior claims manager with expertise in routing and prioritization. You analyze claim data and direct each claim to the right specialized team.",
        allow_delegation=True,
        verbose=True,
        llm=llm,
    )
