"""New claim workflow crew.

Formal specification: docs/crews.md#new-claim-crew (Issue #64).
Flow: Intake (validate) -> Policy (query_policy_db) -> Assignment (claim_id, generate_report).
"""

from claim_agent.agents.new_claim import (
    create_assignment_agent,
    create_intake_agent,
    create_policy_checker_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_new_claim_crew(llm: LLMProtocol | None = None):
    """Create the New Claim crew: intake -> policy check -> assignment."""
    return create_crew(
        agents_config=[
            AgentConfig(create_intake_agent),
            AgentConfig(create_policy_checker_agent),
            AgentConfig(create_assignment_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Step 1: Ensure all required fields are present in the claim data (policy_number, vin, vehicle_year, vehicle_make, vehicle_model, incident_date, incident_description, damage_description).
Step 2: Check data types and formats are valid.""",
                expected_output="Validation result: either 'valid' with no missing fields, or a list of missing/invalid fields.",
                agent_index=0,
            ),
            TaskConfig(
                description="""Query the policy database for the policy_number from the claim data.
Verify the policy is active and has valid coverage.
Use the query_policy_db tool.""",
                expected_output="Policy validity and coverage details (valid/invalid, coverage type, deductible).",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""Use the claim_id from claim_data if provided; otherwise generate one with the generate_claim_id tool (prefix CLM).
Set initial status to 'open'.
Generate a brief claim report using generate_report with claim_id, claim_type='new', status='open', and a short summary of actions taken.""",
                expected_output="Claim ID (e.g. CLM-XXXXXXXX), status confirmation, and a one-line summary.",
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
    )
