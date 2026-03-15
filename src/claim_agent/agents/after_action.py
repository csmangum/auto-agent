"""Agents for the after-action workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.tools import (
    add_after_action_note,
    close_claim,
    get_claim_notes,
    get_claim_tasks,
)
from claim_agent.skills import (
    AFTER_ACTION_SUMMARY,
    AFTER_ACTION_STATUS,
    load_skill,
)


def create_after_action_summary_agent(
    llm: LLMProtocol | None = None,
):
    """Create the after-action summary specialist."""
    skill = load_skill(AFTER_ACTION_SUMMARY)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_after_action_note, get_claim_notes, get_claim_tasks],
        verbose=True,
        llm=llm,
    )


def create_after_action_status_agent(
    llm: LLMProtocol | None = None,
):
    """Create the after-action status specialist."""
    skill = load_skill(AFTER_ACTION_STATUS)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[close_claim, get_claim_notes],
        verbose=True,
        llm=llm,
    )
