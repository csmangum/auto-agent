"""Human review handback agent for post-escalation claim processing."""

from crewai import Agent

from claim_agent.tools.handback_tools import (
    get_escalation_context,
    apply_reviewer_decision,
    parse_reviewer_decision,
)
from claim_agent.skills import load_skill, HUMAN_REVIEW_HANDBACK


def create_handback_agent(llm=None):
    """Create the Human Review Handback Specialist agent."""
    skill = load_skill(HUMAN_REVIEW_HANDBACK)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[get_escalation_context, apply_reviewer_decision, parse_reviewer_decision],
        verbose=True,
        llm=llm,
    )
