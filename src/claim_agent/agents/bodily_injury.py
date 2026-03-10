"""Agents for the bodily injury workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.skills import (
    BI_INTAKE_SPECIALIST,
    load_skill,
    MEDICAL_RECORDS_REVIEWER,
    SETTLEMENT_NEGOTIATOR,
)
from claim_agent.tools import (
    add_claim_note,
    assess_injury_severity,
    calculate_bi_settlement,
    escalate_claim,
    get_claim_notes,
    query_medical_records,
)


def create_bi_intake_specialist_agent(llm: LLMProtocol | None = None):
    """BI Intake Specialist: captures injury details at intake."""
    skill = load_skill(BI_INTAKE_SPECIALIST)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            add_claim_note,
            get_claim_notes,
            escalate_claim,
        ],
        verbose=True,
        llm=llm,
    )


def create_medical_records_reviewer_agent(llm: LLMProtocol | None = None):
    """Medical Records Reviewer: reviews medical records and assesses injury severity."""
    skill = load_skill(MEDICAL_RECORDS_REVIEWER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            query_medical_records,
            assess_injury_severity,
            add_claim_note,
            get_claim_notes,
            escalate_claim,
        ],
        verbose=True,
        llm=llm,
    )


def create_settlement_negotiator_agent(llm: LLMProtocol | None = None):
    """Settlement Negotiator: proposes BI settlement within policy limits."""
    skill = load_skill(SETTLEMENT_NEGOTIATOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            calculate_bi_settlement,
            add_claim_note,
            get_claim_notes,
            escalate_claim,
        ],
        verbose=True,
        llm=llm,
    )
