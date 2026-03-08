"""Structural tests for crew and task configuration.

These tests validate crew/task composition without making LLM API calls.
They run in CI without OPENAI_API_KEY.
"""


from crewai import LLM


def _mock_llm():
    """Minimal LLM for structural validation (no API calls)."""
    return LLM(model="gpt-4o-mini", api_key="fake-key-for-structural-test")


def _validate_crew_structure(crew):
    """Assert crew invariants: at least one agent, one task, valid wiring."""
    assert len(crew.agents) >= 1, "Crew must have at least one agent"
    assert len(crew.tasks) >= 1, "Crew must have at least one task"
    for i, task in enumerate(crew.tasks):
        assert task.agent is not None, f"Task {i} must have an agent"
        assert task.agent in crew.agents, f"Task {i} agent must be in crew.agents"
        context = getattr(task, "context", None)
        if isinstance(context, (list, tuple)):
            for ctx_task in context:
                assert ctx_task in crew.tasks[:i], (
                    f"Task {i} context must reference earlier tasks only"
                )


class TestNewClaimCrewStructure:
    """Structural validation for New Claim crew."""

    def test_creates_valid_crew(self):
        from claim_agent.crews.new_claim_crew import create_new_claim_crew

        crew = create_new_claim_crew(llm=_mock_llm())
        _validate_crew_structure(crew)
        assert len(crew.agents) == 3
        assert len(crew.tasks) == 3


class TestDuplicateCrewStructure:
    """Structural validation for Duplicate crew."""

    def test_creates_valid_crew(self):
        from claim_agent.crews.duplicate_crew import create_duplicate_crew

        crew = create_duplicate_crew(llm=_mock_llm())
        _validate_crew_structure(crew)
        assert len(crew.agents) == 3
        assert len(crew.tasks) == 3


class TestTotalLossCrewStructure:
    """Structural validation for Total Loss crew."""

    def test_creates_valid_crew(self):
        from claim_agent.crews.total_loss_crew import create_total_loss_crew

        crew = create_total_loss_crew(llm=_mock_llm(), use_rag=False)
        _validate_crew_structure(crew)
        assert len(crew.agents) == 3
        assert len(crew.tasks) == 3


class TestFraudDetectionCrewStructure:
    """Structural validation for Fraud Detection crew."""

    def test_creates_valid_crew(self):
        from claim_agent.crews.fraud_detection_crew import create_fraud_detection_crew

        crew = create_fraud_detection_crew(llm=_mock_llm())
        _validate_crew_structure(crew)
        assert len(crew.agents) == 3
        assert len(crew.tasks) == 3


class TestPartialLossCrewStructure:
    """Structural validation for Partial Loss crew."""

    def test_creates_valid_crew(self):
        from claim_agent.crews.partial_loss_crew import create_partial_loss_crew

        crew = create_partial_loss_crew(llm=_mock_llm())
        _validate_crew_structure(crew)
        assert len(crew.agents) == 5
        assert len(crew.tasks) == 5


class TestSettlementCrewStructure:
    """Structural validation for Settlement crew."""

    def test_creates_valid_crew(self):
        from claim_agent.crews.settlement_crew import create_settlement_crew

        crew = create_settlement_crew(llm=_mock_llm(), use_rag=False)
        _validate_crew_structure(crew)
        assert len(crew.agents) == 3
        assert len(crew.tasks) == 3


class TestEscalationCrewStructure:
    """Structural validation for Escalation crew."""

    def test_creates_valid_crew(self):
        from claim_agent.crews.escalation_crew import create_escalation_crew

        crew = create_escalation_crew(llm=_mock_llm())
        _validate_crew_structure(crew)
        assert len(crew.agents) == 1
        assert len(crew.tasks) == 1


class TestRouterCrewStructure:
    """Structural validation for Router crew."""

    def test_creates_valid_crew(self):
        from claim_agent.workflow.routing import create_router_crew

        crew = create_router_crew(llm=_mock_llm())
        _validate_crew_structure(crew)
        assert len(crew.agents) == 1
        assert len(crew.tasks) == 1


class TestTaskConfigSchema:
    """Validate TaskConfig and AgentConfig schema."""

    def test_task_config_required_fields(self):
        from claim_agent.crews.factory import TaskConfig

        cfg = TaskConfig(
            description="Do X",
            expected_output="X done",
            agent_index=0,
        )
        assert cfg.description == "Do X"
        assert cfg.expected_output == "X done"
        assert cfg.agent_index == 0
        assert cfg.context_task_indices is None
        assert cfg.output_pydantic is None

    def test_task_config_with_context_and_output(self):
        from claim_agent.crews.factory import TaskConfig
        from claim_agent.models.workflow_output import TotalLossWorkflowOutput

        cfg = TaskConfig(
            description="Task 2",
            expected_output="Output 2",
            agent_index=1,
            context_task_indices=[0],
            output_pydantic=TotalLossWorkflowOutput,
        )
        assert cfg.context_task_indices == [0]
        assert cfg.output_pydantic is TotalLossWorkflowOutput

    def test_agent_config_factory(self):
        from claim_agent.crews.factory import AgentConfig

        def fake_factory(llm=None, **kwargs):
            from crewai import Agent
            return Agent(role="Test", goal="Test", backstory="Test", llm=llm)

        cfg = AgentConfig(fake_factory)
        assert callable(cfg.factory)
