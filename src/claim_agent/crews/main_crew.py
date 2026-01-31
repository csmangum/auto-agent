"""Main crew: router classifies claim, then we run the appropriate workflow crew."""

import json

from crewai import Crew, Task

from claim_agent.agents.router import create_router_agent
from claim_agent.crews.new_claim_crew import create_new_claim_crew
from claim_agent.crews.duplicate_crew import create_duplicate_crew
from claim_agent.crews.total_loss_crew import create_total_loss_crew
from claim_agent.config.llm import get_llm


def create_router_crew(llm=None):
    """Create a crew with only the router agent to classify the claim."""
    llm = llm or get_llm()
    router = create_router_agent(llm)

    classify_task = Task(
        description="""You are given claim_data (JSON) with: policy_number, vin, vehicle_year, vehicle_make, vehicle_model, incident_date, incident_description, damage_description, and optionally estimated_damage.

Classify this claim as exactly one of: new, duplicate, or total_loss.

- new: First-time claim submission, standard intake.
- duplicate: Likely a duplicate of an existing claim (e.g. same incident reported again).
- total_loss: Vehicle damage suggests total loss (e.g. totaled, flood, fire, severe damage, or estimated repair very high).

Reply with exactly one word: new, duplicate, or total_loss. Then on the next line give one sentence reasoning.""",
        expected_output="One line: exactly 'new', 'duplicate', or 'total_loss'. Second line: brief reasoning.",
        agent=router,
    )

    return Crew(
        agents=[router],
        tasks=[classify_task],
        verbose=2,
    )


def create_main_crew(llm=None):
    """Create the main crew (router only). Use run_claim_workflow to classify and run the right sub-crew."""
    return create_router_crew(llm)


def run_claim_workflow(claim_data: dict, llm=None):
    """
    Run the full claim workflow: classify with router crew, then run the appropriate workflow crew.
    claim_data: dict with policy_number, vin, vehicle_year, vehicle_make, vehicle_model, incident_date, incident_description, damage_description, estimated_damage (optional).
    Returns a dict with claim_type, summary, and raw_output from the workflow crew.
    """
    llm = llm or get_llm()
    router_crew = create_router_crew(llm)
    inputs = {"claim_data": json.dumps(claim_data) if isinstance(claim_data, dict) else claim_data}

    # Step 1: Classify
    result = router_crew.kickoff(inputs=inputs)
    raw_output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    raw_output = str(raw_output)
    lines = raw_output.strip().split("\n")
    claim_type = "new"
    for line in lines:
        line = line.strip().lower()
        if line in ("new", "duplicate", "total_loss"):
            claim_type = line
            break
        if line.startswith("new ") or line == "new":
            claim_type = "new"
            break
        if line.startswith("duplicate") or "duplicate" in line and "total_loss" not in line:
            claim_type = "duplicate"
            break
        if line.startswith("total_loss") or "total loss" in line or "total_loss" in line:
            claim_type = "total_loss"
            break

    # Step 2: Run the appropriate crew
    if claim_type == "new":
        crew = create_new_claim_crew(llm)
    elif claim_type == "duplicate":
        crew = create_duplicate_crew(llm)
    else:
        crew = create_total_loss_crew(llm)

    workflow_result = crew.kickoff(inputs=inputs)
    workflow_output = getattr(workflow_result, "raw", None) or getattr(workflow_result, "output", None) or str(workflow_result)
    workflow_output = str(workflow_output)

    return {
        "claim_type": claim_type,
        "router_output": raw_output,
        "workflow_output": workflow_output,
        "summary": workflow_output[:500] + "..." if len(workflow_output) > 500 else workflow_output,
    }
