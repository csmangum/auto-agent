"""Duplicate claim workflow crew."""

from claim_agent.agents.duplicate import (
    create_resolution_agent,
    create_search_agent,
    create_similarity_agent,
)
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_duplicate_crew(llm=None):
    """Create the Duplicate Checker crew: search -> similarity -> resolution."""
    return create_crew(
        agents_config=[
            AgentConfig(create_search_agent),
            AgentConfig(create_similarity_agent),
            AgentConfig(create_resolution_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Search existing claims using the claim_data above.
Use search_claims_db with vin and incident_date from the claim.
Return the list of matching or similar claims.""",
                expected_output="List of existing claims matching the same VIN and incident date (or empty list).",
                agent_index=0,
            ),
            TaskConfig(
                description="""Compare the incident_description from the current claim with the incident descriptions of any claims found in the search.
Use the compute_similarity tool. If similarity > 80%, flag as duplicate.
Summarize: similarity score and whether this is likely a duplicate.""",
                expected_output="Similarity score (0-100), is_duplicate (true/false), and brief reasoning.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""Based on the similarity result: if similarity > 80%, decide to merge or reject the duplicate.
If merge: recommend merging with the existing claim. If reject: recommend rejecting as duplicate.
Provide a clear resolution decision and one-line summary for the output.""",
                expected_output="Resolution: 'merge' or 'reject', with a one-line summary.",
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
    )
