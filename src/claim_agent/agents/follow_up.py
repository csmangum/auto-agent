"""Agents for the follow-up workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.skills import (
    FOLLOW_UP_OUTREACH,
    MESSAGE_COMPOSITION,
    RESPONSE_PROCESSING,
    load_skill,
)
from claim_agent.tools import (
    add_claim_note,
    check_pending_responses,
    create_claim_task,
    get_claim_notes,
    get_claim_tasks,
    record_user_response,
    send_user_message,
)


def create_outreach_planner_agent(llm: LLMProtocol | None = None, **kwargs) -> Agent:
    """Outreach Planner: identifies user type and plans follow-up tasks."""
    skill = load_skill(FOLLOW_UP_OUTREACH)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[send_user_message, check_pending_responses, get_claim_notes, create_claim_task, get_claim_tasks],
        verbose=True,
        llm=llm,
    )


def create_message_composer_agent(llm: LLMProtocol | None = None, **kwargs) -> Agent:
    """Message Composer: drafts and sends tailored outreach messages."""
    skill = load_skill(MESSAGE_COMPOSITION)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[send_user_message, check_pending_responses, get_claim_notes, create_claim_task],
        verbose=True,
        llm=llm,
    )


def create_response_processor_agent(llm: LLMProtocol | None = None, **kwargs) -> Agent:
    """Response Processor: processes user responses and updates claim context."""
    skill = load_skill(RESPONSE_PROCESSING)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[check_pending_responses, record_user_response, add_claim_note, get_claim_notes],
        verbose=True,
        llm=llm,
    )
