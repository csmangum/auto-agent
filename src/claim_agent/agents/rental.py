"""Agents for the rental reimbursement workflow (loss-of-use coverage)."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.tools import (
    add_claim_note,
    check_rental_coverage,
    create_document_request,
    escalate_claim,
    get_claim_notes,
    get_rental_limits,
    process_rental_reimbursement,
    query_policy_db,
    record_claim_payment,
    search_state_compliance,
)
from claim_agent.skills import (
    load_skill,
    RENTAL_ELIGIBILITY_SPECIALIST,
    RENTAL_COORDINATOR,
    RENTAL_REIMBURSEMENT_PROCESSOR,
)


def create_rental_eligibility_specialist_agent(llm: LLMProtocol | None = None):
    """Rental Eligibility Specialist: checks policy for rental coverage and limits."""
    skill = load_skill(RENTAL_ELIGIBILITY_SPECIALIST)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            query_policy_db,
            check_rental_coverage,
            get_rental_limits,
            search_state_compliance,
            add_claim_note,
            get_claim_notes,
            escalate_claim,
        ],
        verbose=True,
        llm=llm,
    )


def create_rental_coordinator_agent(llm: LLMProtocol | None = None):
    """Rental Coordinator: arranges and approves rental within policy limits."""
    skill = load_skill(RENTAL_COORDINATOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            get_rental_limits,
            create_document_request,
            add_claim_note,
            get_claim_notes,
            escalate_claim,
        ],
        verbose=True,
        llm=llm,
    )


def create_rental_reimbursement_processor_agent(llm: LLMProtocol | None = None):
    """Reimbursement Processor: processes rental reimbursement for approved rentals."""
    skill = load_skill(RENTAL_REIMBURSEMENT_PROCESSOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            process_rental_reimbursement,
            record_claim_payment,
            get_rental_limits,
            add_claim_note,
            get_claim_notes,
            escalate_claim,
        ],
        verbose=True,
        llm=llm,
    )
