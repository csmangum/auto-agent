"""Agents for the new claim workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.skills import load_skill, INTAKE, POLICY_CHECKER, ASSIGNMENT
from claim_agent.tools import add_claim_note, escalate_claim, generate_claim_id, generate_report, get_claim_notes, query_policy_db


def create_intake_agent(llm: LLMProtocol | None = None):
    """Intake Specialist: validates claim data."""
    skill = load_skill(INTAKE)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_claim_note, escalate_claim, get_claim_notes],
        verbose=True,
        llm=llm,
    )


def create_policy_checker_agent(llm: LLMProtocol | None = None):
    """Policy Verification Specialist: queries policy DB."""
    skill = load_skill(POLICY_CHECKER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_claim_note, get_claim_notes, query_policy_db, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_assignment_agent(llm: LLMProtocol | None = None):
    """Claim Assignment Specialist: generates claim ID and updates status."""
    skill = load_skill(ASSIGNMENT)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_claim_note, generate_claim_id, generate_report, get_claim_notes, escalate_claim],
        verbose=True,
        llm=llm,
    )
