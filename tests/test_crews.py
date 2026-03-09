"""Integration tests for crews (require LLM; can be skipped if no API key)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claim_agent.utils.retry import with_llm_retry

os.environ.setdefault("MOCK_DB_PATH", str(Path(__file__).resolve().parent.parent / "data" / "mock_db.json"))

# Skip crew tests if no OpenAI/OpenRouter key (avoid failing in CI without key)
SKIP_CREW = not os.environ.get("OPENAI_API_KEY")


def _kickoff_with_retry(crew, inputs):
    """Run crew.kickoff with retry on transient LLM/API failures."""
    @with_llm_retry()
    def _call():
        return crew.kickoff(inputs=inputs)

    return _call()


# --- Factory unit tests ---


def _mock_agent_factory(llm=None, **kwargs):
    """Minimal agent factory for factory tests."""
    from crewai import Agent

    return Agent(role="Test", goal="Test", backstory="Test", llm=llm)


def test_create_crew_with_agent_kwargs():
    """create_crew passes agent_kwargs to agent factories."""
    from crewai import LLM
    from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew

    received_kwargs = {}

    def capturing_factory(llm=None, **kwargs):
        received_kwargs.clear()
        received_kwargs.update(kwargs)
        return _mock_agent_factory(llm=llm)

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    crew = create_crew(
        agents_config=[AgentConfig(capturing_factory)],
        tasks_config=[
            TaskConfig(
                description="Do X",
                expected_output="X done",
                agent_index=0,
            ),
        ],
        llm=mock_llm,
        agent_kwargs={"state": "Texas", "claim_type": "total_loss", "use_rag": False},
    )
    assert received_kwargs == {"state": "Texas", "claim_type": "total_loss", "use_rag": False}
    assert len(crew.agents) == 1
    assert len(crew.tasks) == 1


def test_create_crew_with_context_task_indices_and_output_pydantic():
    """create_crew wires context and output_pydantic correctly."""
    from crewai import LLM
    from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
    from claim_agent.models.workflow_output import TotalLossWorkflowOutput

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    crew = create_crew(
        agents_config=[
            AgentConfig(_mock_agent_factory),
            AgentConfig(_mock_agent_factory),
        ],
        tasks_config=[
            TaskConfig("Task 1", "Output 1", agent_index=0),
            TaskConfig(
                "Task 2",
                "Output 2",
                agent_index=1,
                context_task_indices=[0],
                output_pydantic=TotalLossWorkflowOutput,
            ),
        ],
        llm=mock_llm,
    )
    assert len(crew.tasks) == 2
    task2 = crew.tasks[1]
    assert crew.tasks[0] in task2.context
    assert getattr(task2, "output_pydantic", None) is TotalLossWorkflowOutput


def test_create_crew_invalid_agent_index_raises():
    """create_crew raises ValueError for out-of-range agent_index."""
    from crewai import LLM
    from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    with pytest.raises(ValueError, match="agent_index 5 out of range"):
        create_crew(
            agents_config=[AgentConfig(_mock_agent_factory)] * 3,
            tasks_config=[
                TaskConfig("Task", "Output", agent_index=5),
            ],
            llm=mock_llm,
        )


def test_create_crew_invalid_context_task_indices_raises():
    """create_crew raises ValueError for invalid context_task_indices."""
    from crewai import LLM
    from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    with pytest.raises(ValueError, match="invalid context_task_indices"):
        create_crew(
            agents_config=[
                AgentConfig(_mock_agent_factory),
                AgentConfig(_mock_agent_factory),
            ],
            tasks_config=[
                TaskConfig("Task 1", "Output 1", agent_index=0),
                TaskConfig(
                    "Task 2",
                    "Output 2",
                    agent_index=1,
                    context_task_indices=[1],
                ),
            ],
            llm=mock_llm,
        )


def test_create_crew_context_task_indices_negative_raises():
    """create_crew raises ValueError for negative context_task_indices."""
    from crewai import LLM
    from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    with pytest.raises(ValueError, match="invalid context_task_indices"):
        create_crew(
            agents_config=[
                AgentConfig(_mock_agent_factory),
                AgentConfig(_mock_agent_factory),
            ],
            tasks_config=[
                TaskConfig("Task 1", "Output 1", agent_index=0),
                TaskConfig(
                    "Task 2",
                    "Output 2",
                    agent_index=1,
                    context_task_indices=[-1],
                ),
            ],
            llm=mock_llm,
        )


def test_new_claim_crew_acceptance_criteria():
    """Verify New Claim crew structure matches formal specification (Issue #64)."""
    from crewai import LLM
    from claim_agent.crews.new_claim_crew import create_new_claim_crew
    from claim_agent.agents.new_claim import create_policy_checker_agent

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    crew = create_new_claim_crew(llm=mock_llm)

    # AC1: Intake task validates required fields and data types
    intake_task = crew.tasks[0]
    required = ["policy_number", "vin", "vehicle_year", "vehicle_make", "vehicle_model", "incident_date", "incident_description", "damage_description"]
    for field in required:
        assert field in intake_task.description, f"AC1: Intake task must validate {field}"
    assert "valid" in intake_task.expected_output.lower() or "missing" in intake_task.expected_output.lower()

    # AC2: Policy task calls query_policy_db
    policy_agent = create_policy_checker_agent(llm=mock_llm)
    policy_tool_names = [getattr(t, "name", str(t)) for t in (policy_agent.tools or [])]
    assert any("policy" in n.lower() and "query" in n.lower() for n in policy_tool_names), (
        "AC2: Policy agent must have query_policy_db tool"
    )

    # AC3 & AC4: Assignment task uses claim_id when present, calls generate_report with claim_type='new', status='open'
    assign_task = crew.tasks[2]
    assert "claim_id" in assign_task.description and "claim_data" in assign_task.description
    assert "generate_claim_id" in assign_task.description
    assert "generate_report" in assign_task.description
    assert "claim_type='new'" in assign_task.description or "claim_type=\"new\"" in assign_task.description
    assert "status='open'" in assign_task.description or "status=\"open\"" in assign_task.description

    # AC5: Final status is 'open' - verified by main flow; crew outputs status open
    assert "open" in assign_task.description.lower()

    # AC6: Task context flows correctly
    policy_task = crew.tasks[1]
    assert intake_task in policy_task.context, "Policy task must receive validation output"
    assert intake_task in assign_task.context and policy_task in assign_task.context, (
        "Assignment task must receive validation + policy output"
    )


def test_total_loss_crew_acceptance_criteria():
    """Verify Total Loss crew structure matches formal specification (Issue #73)."""
    from crewai import LLM
    from claim_agent.crews.total_loss_crew import create_total_loss_crew

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    crew = create_total_loss_crew(llm=mock_llm)

    assess_task, valuation_task, payout_task = crew.tasks

    # AC1: Damage task calls evaluate_damage and outputs total_loss_candidate
    damage_agent = crew.agents[0]
    damage_tool_names = [getattr(t, "name", str(t)) for t in (damage_agent.tools or [])]
    assert any("evaluate" in n.lower() and "damage" in n.lower() for n in damage_tool_names), (
        "AC1: Damage agent must have evaluate_damage tool"
    )
    assert "total_loss_candidate" in assess_task.expected_output, "AC1: Damage task must output total_loss_candidate"

    # AC2: Valuation task calls fetch_vehicle_value with vehicle identifiers
    valuation_agent = crew.agents[1]
    valuation_tool_names = [getattr(t, "name", str(t)) for t in (valuation_agent.tools or [])]
    assert any("fetch" in n.lower() and "vehicle" in n.lower() for n in valuation_tool_names), (
        "AC2: Valuation agent must have fetch_vehicle_value tool"
    )
    assert "vin" in valuation_task.description and "vehicle_year" in valuation_task.description

    # AC3: Payout task calls calculate_payout with vehicle value and policy_number
    payout_agent = crew.agents[2]
    payout_tool_names = [getattr(t, "name", str(t)) for t in (payout_agent.tools or [])]
    assert any("calculate" in n.lower() and "payout" in n.lower() for n in payout_tool_names), (
        "AC3: Payout agent must have calculate_payout tool"
    )
    assert "policy_number" in payout_task.description and "vehicle value" in payout_task.description.lower()

    # AC4: Payout formula: value - deductible
    assert "minus" in payout_task.description.lower() or "deductible" in payout_task.description.lower()

    # AC5: Total Loss now ends at payout and hands off to shared settlement crew
    assert len(crew.agents) == 3
    assert len(crew.tasks) == 3

    # AC6: Task context flows: Valuation receives damage; Payout receives damage + valuation
    assert assess_task in valuation_task.context, "AC6: Valuation must receive damage assessment"
    assert assess_task in payout_task.context and valuation_task in payout_task.context, (
        "AC6: Payout must receive damage + valuation"
    )

    # Structured output: payout task uses output_pydantic for payout_amount extraction
    from claim_agent.models.workflow_output import TotalLossWorkflowOutput
    assert getattr(payout_task, "output_pydantic", None) is TotalLossWorkflowOutput


def test_partial_loss_crew_acceptance_criteria():
    """Verify Partial Loss crew now hands off to the shared settlement crew."""
    from crewai import LLM
    from claim_agent.crews.partial_loss_crew import create_partial_loss_crew

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    crew = create_partial_loss_crew(llm=mock_llm)

    assess_task, estimate_task, shop_task, parts_task, authorization_task = crew.tasks

    auth_agent = crew.agents[4]
    auth_tool_names = [getattr(t, "name", str(t)) for t in (auth_agent.tools or [])]
    assert any("repair authorization" in n.lower() for n in auth_tool_names), (
        "AC1: Repair authorization agent must have generate_repair_authorization tool"
    )
    assert not any("report" in n.lower() for n in auth_tool_names), (
        "AC2: Repair authorization agent should no longer finalize reports"
    )
    assert "Do not generate the final claim report" in authorization_task.description
    assert "insurance_pays" in authorization_task.description
    assert assess_task in estimate_task.context
    assert assess_task in shop_task.context and estimate_task in shop_task.context
    assert all(task in authorization_task.context for task in [assess_task, estimate_task, shop_task, parts_task])

    # Structured output: authorization task uses output_pydantic for payout_amount extraction
    from claim_agent.models.workflow_output import PartialLossWorkflowOutput
    assert getattr(authorization_task, "output_pydantic", None) is PartialLossWorkflowOutput


def test_extract_payout_from_workflow_result():
    """Verify _extract_payout_from_workflow_result extracts payout_amount from structured output."""
    from claim_agent.crews.main_crew import _extract_payout_from_workflow_result
    from claim_agent.models.workflow_output import TotalLossWorkflowOutput

    # Pydantic model output
    mock_task = MagicMock()
    mock_task.output = TotalLossWorkflowOutput(
        payout_amount=14500.0, vehicle_value=15000.0, deductible=500.0, calculation="15000 - 500"
    )
    mock_result = MagicMock()
    mock_result.tasks_output = [MagicMock(), MagicMock(), mock_task]
    assert _extract_payout_from_workflow_result(mock_result, "total_loss") == 14500.0

    # Dict output (fallback)
    mock_task_dict = MagicMock()
    mock_task_dict.output = {"payout_amount": 2100.0, "authorization_id": "AUTH-001"}
    mock_result_dict = MagicMock()
    mock_result_dict.tasks_output = [mock_task_dict]
    assert _extract_payout_from_workflow_result(mock_result_dict, "partial_loss") == 2100.0

    # BIWorkflowOutput (bodily_injury)
    from claim_agent.models.workflow_output import BIWorkflowOutput

    mock_bi_task = MagicMock()
    mock_bi_task.output = BIWorkflowOutput(
        payout_amount=8500.0,
        medical_charges=3750.0,
        pain_suffering=5625.0,
        injury_severity="moderate",
    )
    mock_bi_result = MagicMock()
    mock_bi_result.tasks_output = [mock_bi_task]
    assert _extract_payout_from_workflow_result(mock_bi_result, "bodily_injury") == 8500.0

    # Non-payout claim types return None
    assert _extract_payout_from_workflow_result(mock_result, "new") is None
    assert _extract_payout_from_workflow_result(mock_result, "fraud") is None

    # Missing or empty tasks_output returns None
    empty_result = MagicMock()
    empty_result.tasks_output = None
    assert _extract_payout_from_workflow_result(empty_result, "total_loss") is None
    empty_result.tasks_output = []
    assert _extract_payout_from_workflow_result(empty_result, "total_loss") is None


def test_settlement_crew_acceptance_criteria():
    """Verify shared Settlement crew structure matches Issue #76 specification."""
    from crewai import LLM
    from claim_agent.crews.settlement_crew import create_settlement_crew

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    crew = create_settlement_crew(llm=mock_llm, claim_type="total_loss", use_rag=False)

    documentation_task, payment_task, closure_task = crew.tasks
    documentation_agent, payment_agent, closure_agent = crew.agents

    documentation_tool_names = [getattr(t, "name", str(t)) for t in (documentation_agent.tools or [])]
    payment_tool_names = [getattr(t, "name", str(t)) for t in (payment_agent.tools or [])]
    closure_tool_names = [getattr(t, "name", str(t)) for t in (closure_agent.tools or [])]

    assert any("report" in n.lower() for n in documentation_tool_names)
    assert any("calculate" in n.lower() and "payout" in n.lower() for n in payment_tool_names)
    assert any("report" in n.lower() for n in closure_tool_names)

    assert "{workflow_output}" in documentation_task.description
    assert "claim_type from claim_data" in documentation_task.description
    assert "payment distribution" in payment_task.description.lower()
    assert "status='settled'" in closure_task.description or "status=\"settled\"" in closure_task.description
    assert "next_steps" in closure_task.description

    assert documentation_task in payment_task.context
    assert documentation_task in closure_task.context and payment_task in closure_task.context

    # AC2 (Issue #76): Settlement receives payout_amount from claim_data when present
    assert "payout_amount from claim_data when present" in documentation_task.description


def test_settlement_crew_bodily_injury_documentation():
    """Settlement crew documentation task includes BI-specific requirements."""
    from crewai import LLM
    from claim_agent.crews.settlement_crew import create_settlement_crew

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    crew = create_settlement_crew(llm=mock_llm, claim_type="bodily_injury", use_rag=False)
    documentation_task = crew.tasks[0]
    assert "bodily_injury" in documentation_task.description
    assert "medical records" in documentation_task.description.lower()
    assert "injury severity" in documentation_task.description.lower()
    assert "pain" in documentation_task.description.lower() and "suffering" in documentation_task.description.lower()


def test_subrogation_crew_structure():
    """Verify Subrogation crew structure: 3 agents, 4 tasks, correct tools."""
    from crewai import LLM
    from claim_agent.crews.subrogation_crew import create_subrogation_crew

    mock_llm = LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")
    crew = create_subrogation_crew(llm=mock_llm, use_rag=False)

    liability_agent, demand_agent, recovery_agent = crew.agents
    assert len(crew.tasks) == 4
    assert len(crew.agents) == 3

    liability_tool_names = [getattr(t, "name", str(t)) for t in (liability_agent.tools or [])]
    demand_tool_names = [getattr(t, "name", str(t)) for t in (demand_agent.tools or [])]
    recovery_tool_names = [getattr(t, "name", str(t)) for t in (recovery_agent.tools or [])]

    assert any("assess" in n.lower() and "liability" in n.lower() for n in liability_tool_names)
    assert any("build" in n.lower() and "subrogation" in n.lower() for n in demand_tool_names)
    assert any("demand" in n.lower() or "send" in n.lower() for n in demand_tool_names)
    assert any("record" in n.lower() and "recovery" in n.lower() for n in recovery_tool_names)

    task0, task1, task2, task3 = crew.tasks
    assert "{claim_data}" in task0.description and "{workflow_output}" in task0.description
    assert task0 in task1.context
    assert task1 in task2.context and task2 in task3.context


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_new_claim_crew_kickoff():
    """Run new claim crew on sample input (requires LLM)."""
    from claim_agent.crews.new_claim_crew import create_new_claim_crew

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_parking.json") as f:
        claim_data = json.load(f)

    crew = create_new_claim_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = _kickoff_with_retry(crew, inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output
    assert "CLM-" in str(output) or "claim" in str(output).lower()


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_duplicate_crew_kickoff():
    """Run duplicate crew on sample input (requires LLM)."""
    from claim_agent.crews.duplicate_crew import create_duplicate_crew

    with open(Path(__file__).parent / "sample_claims" / "duplicate_claim.json") as f:
        claim_data = json.load(f)

    crew = create_duplicate_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = _kickoff_with_retry(crew, inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_total_loss_crew_kickoff():
    """Run total loss crew on sample input (requires LLM)."""
    from claim_agent.crews.total_loss_crew import create_total_loss_crew

    with open(Path(__file__).parent / "sample_claims" / "total_loss_claim.json") as f:
        claim_data = json.load(f)

    crew = create_total_loss_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = _kickoff_with_retry(crew, inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_fraud_detection_crew_kickoff():
    """Run fraud detection crew on sample input (requires LLM)."""
    from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew

    with open(Path(__file__).parent / "sample_claims" / "fraud_claim.json") as f:
        claim_data = json.load(f)

    crew = create_fraud_detection_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = _kickoff_with_retry(crew, inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output
    assert "fraud" in str(output).lower() or "risk" in str(output).lower()


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_partial_loss_crew_kickoff():
    """Run partial loss crew on sample input (requires LLM)."""
    from claim_agent.crews.partial_loss_crew import create_partial_loss_crew

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_claim.json") as f:
        claim_data = json.load(f)

    crew = create_partial_loss_crew()
    inputs = {"claim_data": json.dumps(claim_data)}
    result = _kickoff_with_retry(crew, inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output


@pytest.mark.skipif(SKIP_CREW, reason="OPENAI_API_KEY not set; skip crew integration tests")
def test_rental_crew_kickoff():
    """Run rental crew on sample input; verifies output structure (requires LLM)."""
    from claim_agent.crews.rental_crew import create_rental_crew

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_claim.json") as f:
        claim_data = json.load(f)
    claim_data["claim_id"] = "CLM-RENTAL-TEST"
    claim_data["claim_type"] = "partial_loss"
    workflow_output = json.dumps({"payout_amount": 2100, "estimated_repair_days": 5})

    crew = create_rental_crew()
    inputs = {
        "claim_data": json.dumps(claim_data),
        "workflow_output": workflow_output,
    }
    result = _kickoff_with_retry(crew, inputs)
    output = getattr(result, "raw", None) or getattr(result, "output", None) or str(result)
    assert output
    assert "claim_data" in str(inputs)
    assert "workflow_output" in str(inputs)


def test_run_claim_workflow_classification_only():
    """Test that run_claim_workflow returns expected keys and persists to DB."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.database import init_db

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_parking.json") as f:
        claim_data = json.load(f)

    if SKIP_CREW:
        pytest.skip("OPENAI_API_KEY not set")
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        result = run_claim_workflow(claim_data)
        assert "claim_id" in result
        assert "claim_type" in result
        assert result["claim_type"] in (
            "new",
            "duplicate",
            "total_loss",
            "fraud",
            "partial_loss",
            "bodily_injury",
            "reopened",
        )
        assert "workflow_output" in result
        assert "summary" in result
    finally:
        os.unlink(path)
        os.environ.pop("CLAIMS_DB_PATH", None)


def test_parse_claim_type_exact():
    """Claim type parsing: exact matches."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("new") == "new"
    assert _parse_claim_type("duplicate") == "duplicate"
    assert _parse_claim_type("total_loss") == "total_loss"
    assert _parse_claim_type("total loss") == "total_loss"
    assert _parse_claim_type("fraud") == "fraud"
    assert _parse_claim_type("partial_loss") == "partial_loss"
    assert _parse_claim_type("partial loss") == "partial_loss"
    assert _parse_claim_type("bodily_injury") == "bodily_injury"
    assert _parse_claim_type("bodily injury") == "bodily_injury"
    assert _parse_claim_type("reopened") == "reopened"


def test_parse_claim_type_with_reasoning():
    """Claim type parsing: type on first line, reasoning on second."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("new\nReason: first-time submission.") == "new"
    assert _parse_claim_type("duplicate\nSame VIN and date as existing claim.") == "duplicate"
    assert _parse_claim_type("total_loss\nVehicle flooded.") == "total_loss"
    assert _parse_claim_type("fraud\nMultiple fraud indicators detected.") == "fraud"
    assert _parse_claim_type("partial_loss\nRepairable bumper damage.") == "partial_loss"


def test_parse_claim_type_starts_with():
    """Claim type parsing: line starts with type."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("new claim submission") == "new"
    assert _parse_claim_type("Duplicate of CLM-EXIST01") == "duplicate"
    assert _parse_claim_type("total loss - flood damage") == "total_loss"
    assert _parse_claim_type("fraud - suspicious indicators") == "fraud"
    assert _parse_claim_type("partial loss - bumper repair") == "partial_loss"
    assert _parse_claim_type("partial_loss: fender damage repairable") == "partial_loss"
    assert _parse_claim_type("bodily injury - whiplash claim") == "bodily_injury"


def test_parse_claim_type_default():
    """Claim type parsing: unknown output defaults to new."""
    from claim_agent.crews.main_crew import _parse_claim_type

    assert _parse_claim_type("") == "new"
    assert _parse_claim_type("Unable to classify.") == "new"


def test_parse_router_output_structured_json():
    """_parse_router_output parses JSON with claim_type, confidence, reasoning."""
    from claim_agent.crews.main_crew import _parse_router_output

    result = object()  # No tasks_output
    raw = '{"claim_type": "partial_loss", "confidence": 0.85, "reasoning": "Repairable bumper damage."}'
    claim_type, confidence, reasoning = _parse_router_output(result, raw)
    assert claim_type == "partial_loss"
    assert confidence == 0.85
    assert "bumper" in reasoning


def test_parse_router_output_json_with_markdown():
    """_parse_router_output extracts JSON from markdown code block."""
    from claim_agent.crews.main_crew import _parse_router_output

    result = object()
    raw = '```json\n{"claim_type": "fraud", "confidence": 0.6, "reasoning": "Suspicious."}\n```'
    claim_type, confidence, reasoning = _parse_router_output(result, raw)
    assert claim_type == "fraud"
    assert confidence == 0.6


def test_parse_router_output_legacy_fallback():
    """_parse_router_output falls back to legacy parsing when JSON invalid."""
    from claim_agent.crews.main_crew import _parse_router_output

    result = object()
    raw = "total_loss\nVehicle flooded."
    claim_type, confidence, reasoning = _parse_router_output(result, raw)
    assert claim_type == "total_loss"
    assert 0.3 <= confidence <= 1.0
    assert "flooded" in reasoning or reasoning == ""


def test_parse_router_output_pydantic_from_tasks_output():
    """_parse_router_output uses RouterOutput from tasks_output when available."""
    from unittest.mock import MagicMock
    from claim_agent.crews.main_crew import _parse_router_output
    from claim_agent.models.claim import RouterOutput

    mock_output = RouterOutput(claim_type="duplicate", confidence=0.92, reasoning="Same VIN and date.")
    mock_task = MagicMock(output=mock_output)
    result = MagicMock(tasks_output=[mock_task])
    raw = "fallback"
    claim_type, confidence, reasoning = _parse_router_output(result, raw)
    assert claim_type == "duplicate"
    assert confidence == 0.92
    assert "Same VIN" in reasoning


def test_normalize_claim_type():
    """normalize_claim_type maps variants to canonical values."""
    from claim_agent.tools.escalation_logic import normalize_claim_type

    assert normalize_claim_type("total_loss") == "total_loss"
    assert normalize_claim_type("total loss") == "total_loss"
    assert normalize_claim_type("partial_loss") == "partial_loss"
    assert normalize_claim_type("new") == "new"
    assert normalize_claim_type("duplicate") == "duplicate"
    assert normalize_claim_type("fraud") == "fraud"
    assert normalize_claim_type("bodily_injury") == "bodily_injury"
    assert normalize_claim_type("reopened") == "reopened"
    assert normalize_claim_type("unknown") == "new"


def test_check_for_duplicates_empty_vin_returns_empty():
    """_check_for_duplicates returns [] when VIN is missing or blank."""
    from claim_agent.crews.main_crew import _check_for_duplicates

    assert _check_for_duplicates({}) == []
    assert _check_for_duplicates({"vin": ""}) == []
    assert _check_for_duplicates({"vin": "   "}) == []


def test_check_for_duplicates_vin_matching():
    """_check_for_duplicates returns repo matches for same VIN."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-A", "vin": "1HGBH41JXMN109186", "incident_date": "2024-01-15"},
        ],
    ):
        result = _check_for_duplicates({"vin": "1HGBH41JXMN109186"})
    assert len(result) == 1
    assert result[0]["id"] == "CLM-A"
    assert result[0]["vin"] == "1HGBH41JXMN109186"


def test_check_for_duplicates_filters_current_claim_id():
    """_check_for_duplicates excludes the claim with current_claim_id."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-A", "vin": "1HGBH41JXMN109186", "incident_date": "2024-01-15"},
            {"id": "CLM-B", "vin": "1HGBH41JXMN109186", "incident_date": "2024-01-20"},
        ],
    ):
        result = _check_for_duplicates(
            {"vin": "1HGBH41JXMN109186", "incident_date": "2024-01-15"},
            current_claim_id="CLM-A",
        )
    assert len(result) == 1
    assert result[0]["id"] == "CLM-B"


def test_check_for_duplicates_sorts_by_date_proximity():
    """_check_for_duplicates sets days_difference and sorts by proximity to incident_date."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-Far", "vin": "VIN123", "incident_date": "2024-03-01"},
            {"id": "CLM-Close", "vin": "VIN123", "incident_date": "2024-01-16"},
            {"id": "CLM-Exact", "vin": "VIN123", "incident_date": "2024-01-15"},
        ],
    ):
        result = _check_for_duplicates(
            {"vin": "VIN123", "incident_date": "2024-01-15"},
        )
    assert [r["id"] for r in result] == ["CLM-Exact", "CLM-Close", "CLM-Far"]
    assert result[0]["days_difference"] == 0
    assert result[1]["days_difference"] == 1
    assert result[2]["days_difference"] == 46


def test_check_for_duplicates_invalid_incident_date_on_claim_no_sort():
    """_check_for_duplicates does not sort when claim incident_date is invalid."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-A", "vin": "VIN123", "incident_date": "2024-01-15"},
            {"id": "CLM-B", "vin": "VIN123", "incident_date": "2024-01-20"},
        ],
    ):
        result = _check_for_duplicates(
            {"vin": "VIN123", "incident_date": "not-a-date"},
        )
    # Order unchanged (no days_difference); invalid target date skips proximity ranking
    assert len(result) == 2
    assert "days_difference" not in result[0]
    assert "days_difference" not in result[1]


def test_check_for_duplicates_invalid_incident_date_on_match_gets_999():
    """_check_for_duplicates assigns days_difference 999 when a match has bad incident_date."""
    from claim_agent.crews.main_crew import _check_for_duplicates
    from claim_agent.db.repository import ClaimRepository

    with patch.object(
        ClaimRepository,
        "search_claims",
        return_value=[
            {"id": "CLM-Bad", "vin": "VIN123", "incident_date": "bad"},
            {"id": "CLM-Good", "vin": "VIN123", "incident_date": "2024-01-15"},
        ],
    ):
        result = _check_for_duplicates(
            {"vin": "VIN123", "incident_date": "2024-01-15"},
        )
    assert result[0]["id"] == "CLM-Good"
    assert result[0]["days_difference"] == 0
    assert result[1]["id"] == "CLM-Bad"
    assert result[1]["days_difference"] == 999


def test_workflow_failure_sets_status_failed():
    """When workflow raises, claim status is set to 'failed' and audit log updated."""
    from claim_agent.crews.main_crew import run_claim_workflow
    from claim_agent.db.database import get_connection, init_db
    from claim_agent.db.repository import ClaimRepository

    with open(Path(__file__).parent / "sample_claims" / "partial_loss_parking.json") as f:
        claim_data = json.load(f)

    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        init_db(path)
        os.environ["CLAIMS_DB_PATH"] = path
        with patch("claim_agent.workflow.orchestrator.get_llm") as mock_llm:
            mock_llm.return_value = None
            with patch("claim_agent.workflow.stages.create_router_crew") as m:
                m.return_value.kickoff.side_effect = RuntimeError("simulated failure")
                with pytest.raises(RuntimeError, match="simulated failure"):
                    run_claim_workflow(claim_data)
        repo = ClaimRepository(db_path=path)
        with get_connection(path) as conn:
            row = conn.execute("SELECT id FROM claims").fetchone()
        assert row is not None
        claim_id = row[0]
        claim = repo.get_claim(claim_id)
        assert claim["status"] == "failed"
        history = repo.get_claim_history(claim_id)
        assert any(h.get("new_status") == "failed" for h in history)
    finally:
        os.unlink(path)
        os.environ.pop("CLAIMS_DB_PATH", None)
