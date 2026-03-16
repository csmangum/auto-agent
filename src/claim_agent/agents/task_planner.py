"""Agent for the task planning workflow stage."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.skills import load_skill, TASK_PLANNER
from claim_agent.tools import (
    create_claim_task,
    update_claim_task,
    get_claim_tasks,
    get_claim_notes,
    get_state_compliance_summary,
    get_compliance_due_date_tool,
)


def create_task_planner_agent(llm: LLMProtocol | None = None) -> Agent:
    """Task Planner: analyzes routed claims and creates follow-up tasks."""
    skill = load_skill(TASK_PLANNER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[
            create_claim_task,
            update_claim_task,
            get_claim_tasks,
            get_claim_notes,
            get_state_compliance_summary,
            get_compliance_due_date_tool,
        ],
        verbose=True,
        llm=llm,
    )
