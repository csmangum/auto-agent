"""Agents for the SIU investigation workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.skills import load_skill
from claim_agent.skills import (
    SIU_DOCUMENT_VERIFICATION,
    SIU_RECORDS_INVESTIGATOR,
    SIU_CASE_MANAGER,
)
from claim_agent.tools import (
    add_claim_note,
    add_siu_investigation_note,
    check_claimant_investigation_history,
    file_fraud_report_state_bureau,
    get_claim_notes,
    get_fraud_detection_guidance,
    get_siu_case_details,
    search_claims_db,
    update_siu_case_status,
    verify_document_authenticity,
)


def create_siu_document_verification_agent(llm: LLMProtocol | None = None) -> Agent:
    """SIU Document Verification Specialist: verifies claim documents."""
    skill = load_skill(SIU_DOCUMENT_VERIFICATION)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            verify_document_authenticity,
            get_siu_case_details,
            add_siu_investigation_note,
            add_claim_note,
        ],
        verbose=True,
        llm=llm,
    )


def create_siu_records_investigator_agent(llm: LLMProtocol | None = None) -> Agent:
    """SIU Records Investigator: checks claimant and vehicle history."""
    skill = load_skill(SIU_RECORDS_INVESTIGATOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            check_claimant_investigation_history,
            search_claims_db,
            get_siu_case_details,
            add_siu_investigation_note,
        ],
        verbose=True,
        llm=llm,
    )


def create_siu_case_manager_agent(llm: LLMProtocol | None = None) -> Agent:
    """SIU Case Manager: synthesizes findings, files state reports, updates case."""
    skill = load_skill(SIU_CASE_MANAGER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            get_siu_case_details,
            add_siu_investigation_note,
            update_siu_case_status,
            file_fraud_report_state_bureau,
            get_fraud_detection_guidance,
            add_claim_note,
            get_claim_notes,
        ],
        verbose=True,
        llm=llm,
    )
