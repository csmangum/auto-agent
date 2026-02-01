"""New claim workflow crew."""

from crewai import Crew, Task

from claim_agent.agents.new_claim import (
    create_intake_agent,
    create_policy_checker_agent,
    create_assignment_agent,
)
from claim_agent.config.llm import get_llm
from claim_agent.config.settings import get_crew_verbose


def create_new_claim_crew(llm=None):
    """Create the New Claim crew: intake -> policy check -> assignment."""
    llm = llm or get_llm()
    intake = create_intake_agent(llm)
    policy = create_policy_checker_agent(llm)
    assignment = create_assignment_agent(llm)

    validate_task = Task(
        description="""Step 1: Ensure all required fields are present in the claim data (policy_number, vin, vehicle_year, vehicle_make, vehicle_model, incident_date, incident_description, damage_description).
Step 2: Check data types and formats are valid.
Use the claim_data from the crew inputs.""",
        expected_output="Validation result: either 'valid' with no missing fields, or a list of missing/invalid fields.",
        agent=intake,
    )

    check_policy_task = Task(
        description="""Query the policy database for the policy_number from the claim data.
Verify the policy is active and has valid coverage.
Use the query_policy_db tool.""",
        expected_output="Policy validity and coverage details (valid/invalid, coverage type, deductible).",
        agent=policy,
        context=[validate_task],
    )

    assign_task = Task(
        description="""Use the claim_id from claim_data if provided; otherwise generate one with the generate_claim_id tool (prefix CLM).
Set initial status to 'open'.
Generate a brief claim report using generate_report with claim_id, claim_type='new', status='open', and a short summary of actions taken.""",
        expected_output="Claim ID (e.g. CLM-XXXXXXXX), status confirmation, and a one-line summary.",
        agent=assignment,
        context=[validate_task, check_policy_task],
    )

    return Crew(
        agents=[intake, policy, assignment],
        tasks=[validate_task, check_policy_task, assign_task],
        verbose=get_crew_verbose(),
    )
