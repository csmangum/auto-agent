"""Agents for the duplicate claim workflow."""

from crewai import Agent

from claim_agent.tools import search_claims_db, compute_similarity
from claim_agent.skills import load_skill, SEARCH, SIMILARITY, RESOLUTION


def create_search_agent(llm=None):
    """Claims Search Specialist: searches existing claims."""
    skill = load_skill(SEARCH)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[search_claims_db],
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
        tools=[compute_similarity],
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
        verbose=True,
        llm=llm,
    )
