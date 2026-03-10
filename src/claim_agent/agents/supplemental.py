"""Agents for the supplemental claim workflow."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.skills import (
    DAMAGE_VERIFIER,
    ESTIMATE_ADJUSTER,
    SUPPLEMENTAL_INTAKE,
    load_skill,
    load_skill_with_context,
)
from claim_agent.tools import (
    calculate_supplemental_estimate,
    evaluate_damage,
    get_original_repair_estimate,
    get_repair_standards,
    query_policy_db,
    update_repair_authorization,
)


def create_supplemental_intake_agent(llm: LLMProtocol | None = None, state: str = "California", **kwargs):
    """Supplemental Intake Specialist: validates report and retrieves original estimate."""
    skill = load_skill_with_context(SUPPLEMENTAL_INTAKE, state=state, use_rag=False)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[get_original_repair_estimate, query_policy_db, get_repair_standards],
        verbose=True,
        llm=llm,
    )


def create_damage_verifier_agent(llm: LLMProtocol | None = None, **kwargs):
    """Damage Verifier: compares supplemental to original scope."""
    skill = load_skill(DAMAGE_VERIFIER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[get_original_repair_estimate, evaluate_damage],
        verbose=True,
        llm=llm,
    )


def create_estimate_adjuster_agent(llm: LLMProtocol | None = None, **kwargs):
    """Estimate Adjuster: calculates supplemental estimate and updates authorization."""
    skill = load_skill(ESTIMATE_ADJUSTER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[calculate_supplemental_estimate, update_repair_authorization],
        verbose=True,
        llm=llm,
    )
