"""Agents for the reopened claim workflow."""

from crewai import Agent

from claim_agent.skills import (
    PRIOR_CLAIM_LOADER,
    REOPENED_ROUTER,
    REOPENED_VALIDATOR,
    load_skill,
)
from claim_agent.tools import (
    evaluate_damage,
    get_claim_notes,
    lookup_original_claim,
    query_policy_db,
)


def create_reopened_validator_agent(llm=None, **kwargs):
    """Reopening Reason Validator: validates reopening reason before proceeding."""
    skill = load_skill(REOPENED_VALIDATOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[query_policy_db, get_claim_notes],
        verbose=True,
        llm=llm,
    )


def create_prior_claim_loader_agent(llm=None, **kwargs):
    """Prior Claim Loader: loads and summarizes the prior settled claim."""
    skill = load_skill(PRIOR_CLAIM_LOADER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[lookup_original_claim],
        verbose=True,
        llm=llm,
    )


def create_reopened_router_agent(llm=None, **kwargs):
    """Reopened Claim Router: routes to partial_loss, total_loss, or bodily_injury."""
    skill = load_skill(REOPENED_ROUTER)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[evaluate_damage, get_claim_notes],
        verbose=True,
        llm=llm,
    )
