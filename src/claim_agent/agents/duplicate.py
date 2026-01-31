"""Agents for the duplicate claim workflow."""

from crewai import Agent

from claim_agent.tools import search_claims_db, compute_similarity


def create_search_agent(llm=None):
    """Claims Search Specialist: searches existing claims."""
    return Agent(
        role="Claims Search Specialist",
        goal="Search existing claims by VIN and incident date for potential duplicates. Use the search_claims_db tool.",
        backstory="Expert at finding related claims in the database. You identify possible duplicate submissions.",
        tools=[search_claims_db],
        verbose=True,
        llm=llm,
    )


def create_similarity_agent(llm=None):
    """Similarity Analyst: compares claim details."""
    return Agent(
        role="Similarity Analyst",
        goal="Compare incident descriptions to determine if claims are duplicates. If similarity > 80%, flag as duplicate. Use compute_similarity tool.",
        backstory="Analytical expert in matching and comparing claim data. You provide similarity scores and duplicate recommendations.",
        tools=[compute_similarity],
        verbose=True,
        llm=llm,
    )


def create_resolution_agent(llm=None):
    """Duplicate Resolution Specialist: decides merge or reject."""
    return Agent(
        role="Duplicate Resolution Specialist",
        goal="Decide whether to merge or reject duplicate claims. If similarity > 80%, prompt for confirmation and then decide merge or reject.",
        backstory="Makes final decisions on duplicate claim handling. You resolve duplicates and document the outcome.",
        verbose=True,
        llm=llm,
    )
