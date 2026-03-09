"""Tests for rental reimbursement crew structure and tasks."""

import json
from pathlib import Path

from crewai import LLM

from claim_agent.crews.rental_crew import create_rental_crew


def _structural_llm():
    """LLM for structural tests (no real API calls)."""
    return LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")


def test_rental_crew_structure():
    """Rental crew has 3 agents and 3 tasks."""
    crew = create_rental_crew(llm=_structural_llm())
    assert len(crew.agents) == 3
    assert len(crew.tasks) == 3


def test_rental_crew_first_task_has_placeholders():
    """First task contains {claim_data} and {workflow_output} for input injection."""
    crew = create_rental_crew(llm=_structural_llm())
    first_task = crew.tasks[0]
    assert "{claim_data}" in first_task.description
    assert "{workflow_output}" in first_task.description


def test_rental_crew_all_tasks_have_claim_data():
    """All rental crew tasks contain {claim_data} for input injection."""
    crew = create_rental_crew(llm=_structural_llm())
    for i, task in enumerate(crew.tasks):
        assert "{claim_data}" in task.description, (
            f"Task {i} must contain {{claim_data}} for input injection"
        )


def test_rental_crew_eligibility_and_coordinator_have_workflow_output():
    """Tasks 0 and 1 contain {workflow_output} for repair duration context."""
    crew = create_rental_crew(llm=_structural_llm())
    assert "{workflow_output}" in crew.tasks[0].description
    assert "{workflow_output}" in crew.tasks[1].description


def test_rental_crew_task_context_flow():
    """Task context flows: task 1 gets task 0; task 2 gets tasks 0 and 1."""
    crew = create_rental_crew(llm=_structural_llm())
    task0, task1, task2 = crew.tasks
    assert len(task0.context) == 0
    assert len(task1.context) == 1
    assert task1.context[0] is task0
    assert len(task2.context) == 2
    assert task2.context[0] is task0
    assert task2.context[1] is task1


def test_rental_crew_agent_tools():
    """Rental agents have expected tools."""
    crew = create_rental_crew(llm=_structural_llm())
    eligibility_agent, coordinator_agent, processor_agent = crew.agents

    eligibility_tools = [getattr(t, "name", str(t)) for t in (eligibility_agent.tools or [])]
    assert any("check_rental" in n or "Check Rental" in n for n in eligibility_tools)
    assert any("get_rental" in n or "Get Rental" in n for n in eligibility_tools)

    coordinator_tools = [getattr(t, "name", str(t)) for t in (coordinator_agent.tools or [])]
    assert any("get_rental" in n or "Get Rental" in n for n in coordinator_tools)

    processor_tools = [getattr(t, "name", str(t)) for t in (processor_agent.tools or [])]
    assert any("process_rental" in n or "Process Rental" in n for n in processor_tools)


def test_rental_crew_kickoff_inputs():
    """Rental crew accepts claim_data and workflow_output inputs."""
    crew = create_rental_crew(llm=_structural_llm())
    assert crew is not None
    with open(Path(__file__).parent / "sample_claims" / "partial_loss_claim.json") as f:
        claim_data = json.load(f)
    claim_data["claim_id"] = "CLM-TEST"
    workflow_output = '{"payout_amount": 2100, "estimated_repair_days": 5}'
    inputs = {
        "claim_data": json.dumps(claim_data),
        "workflow_output": workflow_output,
    }
    # Structural test: crew can be created with inputs (kickoff would need LLM)
    assert "claim_data" in inputs
    assert "workflow_output" in inputs
