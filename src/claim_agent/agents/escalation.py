"""Escalation agent for human-in-the-loop (HITL) review."""

from crewai import Agent

from claim_agent.tools import (
    evaluate_escalation,
    detect_fraud_indicators,
    generate_escalation_report,
)
from claim_agent.skills import load_skill, ESCALATION


def create_escalation_agent(llm=None):
    """Create the Escalation Review Specialist agent that flags cases needing human review."""
    skill = load_skill(ESCALATION)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[evaluate_escalation, detect_fraud_indicators, generate_escalation_report],
        verbose=True,
        llm=llm,
    )
