"""Agents for the claim review (supervisor/compliance) workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.tools import (
    get_claim_notes,
    get_claim_process_context,
    get_compliance_deadlines,
    get_required_disclosures,
    search_california_compliance,
    search_policy_compliance,
)
from claim_agent.skills import (
    CLAIM_REVIEW_SUPERVISOR,
    COMPLIANCE_REVIEW_SPECIALIST,
    load_skill,
    PROCESS_AUDITOR,
)


def create_process_auditor_agent(llm: LLMProtocol | None = None) -> Agent:
    """Create the Process Auditor agent that traces the claim process."""
    skill = load_skill(PROCESS_AUDITOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[get_claim_process_context, get_claim_notes],
        verbose=True,
        llm=llm,
    )


def create_compliance_analyst_agent(llm: LLMProtocol | None = None) -> Agent:
    """Create the Compliance Analyst agent that verifies regulatory compliance."""
    skill = load_skill(COMPLIANCE_REVIEW_SPECIALIST)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            get_claim_process_context,
            search_california_compliance,
            search_policy_compliance,
            get_compliance_deadlines,
            get_required_disclosures,
        ],
        verbose=True,
        llm=llm,
    )


def create_issue_synthesizer_agent(llm: LLMProtocol | None = None) -> Agent:
    """Create the Issue Synthesizer agent that produces the structured review report."""
    skill = load_skill(CLAIM_REVIEW_SUPERVISOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[],
        verbose=True,
        llm=llm,
    )
