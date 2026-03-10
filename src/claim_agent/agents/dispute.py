"""Agents for the policyholder dispute workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.skills import (
    DISPUTE_INTAKE,
    DISPUTE_POLICY_ANALYST,
    DISPUTE_RESOLUTION,
    load_skill,
    load_skill_with_context,
)
from claim_agent.tools import (
    calculate_payout,
    classify_dispute,
    escalate_claim,
    fetch_vehicle_value,
    generate_dispute_report,
    generate_report,
    get_compliance_deadlines,
    get_required_disclosures,
    lookup_original_claim,
    query_policy_db,
    search_policy_compliance,
)
from claim_agent.tools.partial_loss_tools import calculate_repair_estimate


def create_dispute_intake_agent(llm: LLMProtocol | None = None, **kwargs):
    """Dispute Intake Specialist: retrieves original claim and classifies the dispute."""
    skill = load_skill(DISPUTE_INTAKE)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[lookup_original_claim, classify_dispute, query_policy_db, search_policy_compliance],
        verbose=True,
        llm=llm,
    )


def create_dispute_policy_analyst_agent(llm: LLMProtocol | None = None, state: str = "California", **kwargs):
    """Dispute Policy & Compliance Analyst: reviews policy terms and regulatory requirements."""
    skill = load_skill_with_context(DISPUTE_POLICY_ANALYST, state=state)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[query_policy_db, search_policy_compliance, get_compliance_deadlines, get_required_disclosures],
        verbose=True,
        llm=llm,
    )


def create_dispute_resolution_agent(llm: LLMProtocol | None = None, **kwargs):
    """Dispute Resolution Specialist: resolves or escalates the dispute."""
    skill = load_skill(DISPUTE_RESOLUTION)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            fetch_vehicle_value,
            calculate_repair_estimate,
            calculate_payout,
            escalate_claim,
            generate_report,
            generate_dispute_report,
            get_compliance_deadlines,
        ],
        verbose=True,
        llm=llm,
    )
