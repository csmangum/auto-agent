"""Duplicate claim workflow crew."""

from crewai import Crew, Task

from claim_agent.agents.duplicate import (
    create_search_agent,
    create_similarity_agent,
    create_resolution_agent,
)
from claim_agent.config.llm import get_llm
from claim_agent.config.settings import get_crew_verbose


def create_duplicate_crew(llm=None):
    """Create the Duplicate Checker crew: search -> similarity -> resolution."""
    llm = llm or get_llm()
    search_agent = create_search_agent(llm)
    similarity_agent = create_similarity_agent(llm)
    resolution_agent = create_resolution_agent(llm)

    search_task = Task(
        description="""Search existing claims using the claim_data from crew inputs.
Use search_claims_db with vin and incident_date from the claim.
Return the list of matching or similar claims.""",
        expected_output="List of existing claims matching the same VIN and incident date (or empty list).",
        agent=search_agent,
    )

    similarity_task = Task(
        description="""Compare the incident_description from the current claim with the incident descriptions of any claims found in the search.
Use the compute_similarity tool. If similarity > 80%, flag as duplicate.
Summarize: similarity score and whether this is likely a duplicate.""",
        expected_output="Similarity score (0-100), is_duplicate (true/false), and brief reasoning.",
        agent=similarity_agent,
        context=[search_task],
    )

    resolve_task = Task(
        description="""Based on the similarity result: if similarity > 80%, decide to merge or reject the duplicate.
If merge: recommend merging with the existing claim. If reject: recommend rejecting as duplicate.
Provide a clear resolution decision and one-line summary for the output.""",
        expected_output="Resolution: 'merge' or 'reject', with a one-line summary.",
        agent=resolution_agent,
        context=[search_task, similarity_task],
    )

    return Crew(
        agents=[search_agent, similarity_agent, resolution_agent],
        tasks=[search_task, similarity_task, resolve_task],
        verbose=get_crew_verbose(),
    )
