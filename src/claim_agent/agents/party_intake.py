"""Agents for witness and attorney party intake."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.skills import PARTY_INTAKE, load_skill
from claim_agent.tools import (
    create_claim_task,
    create_document_request,
    get_claim_notes,
    record_attorney_representation,
    record_witness_party,
    record_witness_statement,
    send_user_message,
    update_witness_party,
)


def create_party_intake_agent(llm: LLMProtocol | None = None, **kwargs) -> Agent:
    """Single specialist for witness + attorney intake tasks."""
    skill = load_skill(PARTY_INTAKE)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            record_witness_party,
            update_witness_party,
            record_witness_statement,
            record_attorney_representation,
            create_claim_task,
            create_document_request,
            get_claim_notes,
            send_user_message,
        ],
        verbose=True,
        llm=llm,
    )
