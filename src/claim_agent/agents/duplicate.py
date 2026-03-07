"""Agents for the duplicate claim workflow."""

from crewai import Agent

from claim_agent.tools import compute_similarity, escalate_claim, search_claims_db
from claim_agent.skills import load_skill, SEARCH, SIMILARITY, RESOLUTION


def create_search_agent(llm=None):
    """Claims Search Specialist: searches existing claims."""
    skill = load_skill(SEARCH)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[search_claims_db, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_similarity_agent(llm=None):
    """Similarity Analyst: compares claim details."""
    skill = load_skill(SIMILARITY)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[compute_similarity, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_resolution_agent(llm=None):
    """Duplicate Resolution Specialist: decides merge or reject."""
    skill = load_skill(RESOLUTION)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[escalate_claim],
        verbose=True,
        llm=llm,
    )
