"""Agents for the denial and coverage dispute workflow."""

from crewai import Agent

from claim_agent.skills import (
    APPEAL_REVIEWER,
    COVERAGE_ANALYST,
    DENIAL_LETTER_SPECIALIST,
    load_skill,
    load_skill_with_context,
)
from claim_agent.tools import (
    escalate_claim,
    generate_denial_letter,
    generate_report,
    get_coverage_exclusions,
    get_compliance_deadlines,
    get_required_disclosures,
    lookup_original_claim,
    query_policy_db,
    route_to_appeal,
    search_policy_compliance,
)


def create_coverage_analyst_agent(llm=None, state: str = "California", **kwargs):
    """Coverage Analyst: reviews denial reason and verifies coverage/exclusions."""
    skill = load_skill_with_context(COVERAGE_ANALYST, state=state)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            lookup_original_claim,
            query_policy_db,
            get_coverage_exclusions,
            search_policy_compliance,
        ],
        verbose=True,
        llm=llm,
    )


def create_denial_letter_specialist_agent(llm=None, state: str = "California", **kwargs):
    """Denial Letter Specialist: generates compliant denial letters."""
    skill = load_skill_with_context(DENIAL_LETTER_SPECIALIST, state=state)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            generate_denial_letter,
            get_required_disclosures,
            get_compliance_deadlines,
            search_policy_compliance,
        ],
        verbose=True,
        llm=llm,
    )


def create_appeal_reviewer_agent(llm=None, **kwargs):
    """Appeal Reviewer: decides whether to uphold denial or route to appeal."""
    skill = load_skill(APPEAL_REVIEWER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            route_to_appeal,
            escalate_claim,
            generate_report,
            get_compliance_deadlines,
        ],
        verbose=True,
        llm=llm,
    )
