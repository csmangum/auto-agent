"""Agents for the new claim workflow."""

from crewai import Agent

from claim_agent.tools import escalate_claim, generate_claim_id, generate_report, query_policy_db
from claim_agent.skills import load_skill, INTAKE, POLICY_CHECKER, ASSIGNMENT


def create_intake_agent(llm=None):
    """Intake Specialist: validates claim data."""
    skill = load_skill(INTAKE)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_policy_checker_agent(llm=None):
    """Policy Verification Specialist: queries policy DB."""
    skill = load_skill(POLICY_CHECKER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[query_policy_db, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_assignment_agent(llm=None):
    """Claim Assignment Specialist: generates claim ID and updates status."""
    skill = load_skill(ASSIGNMENT)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[generate_claim_id, generate_report, escalate_claim],
        verbose=True,
        llm=llm,
    )
