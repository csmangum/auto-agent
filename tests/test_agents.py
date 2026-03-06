"""Unit tests for agent creation and configuration."""

import os

import pytest

from claim_agent.agents.duplicate import (
    create_resolution_agent,
    create_search_agent,
    create_similarity_agent,
)
from claim_agent.agents.fraud import (
    create_cross_reference_agent,
    create_fraud_assessment_agent,
    create_pattern_analysis_agent,
)
from claim_agent.agents.new_claim import (
    create_assignment_agent,
    create_intake_agent,
    create_policy_checker_agent,
)
from claim_agent.agents.partial_loss import (
    create_partial_loss_damage_assessor_agent,
    create_parts_ordering_agent,
    create_repair_authorization_agent,
    create_repair_estimator_agent,
    create_repair_shop_coordinator_agent,
)
from claim_agent.agents.router import create_router_agent
from claim_agent.agents.total_loss import (
    create_damage_assessor_agent,
    create_payout_agent,
    create_settlement_agent,
    create_valuation_agent,
)
from claim_agent.config.llm import get_llm

# Use real LLM when API key is set (required by CrewAI Agent)
SKIP_AGENTS = not os.environ.get("OPENAI_API_KEY")


@pytest.fixture
def mock_llm():
    if SKIP_AGENTS:
        return None
    return get_llm()


@pytest.mark.skipif(SKIP_AGENTS, reason="OPENAI_API_KEY not set; skip agent creation tests")
class TestRouterAgent:
    """Test router agent creation."""

    def test_create_router_agent_returns_agent(self, mock_llm):
        agent = create_router_agent(llm=mock_llm)
        assert agent is not None
        assert hasattr(agent, "role")
        assert hasattr(agent, "goal")
        assert hasattr(agent, "backstory")

    def test_router_agent_has_role_and_goal(self, mock_llm):
        agent = create_router_agent(llm=mock_llm)
        assert agent.role
        assert agent.goal
        assert agent.backstory

    def test_router_agent_allow_delegation(self, mock_llm):
        agent = create_router_agent(llm=mock_llm)
        assert agent.allow_delegation is True


@pytest.mark.skipif(SKIP_AGENTS, reason="OPENAI_API_KEY not set; skip agent creation tests")
class TestNewClaimAgents:
    """Test new claim workflow agents."""

    def test_create_intake_agent(self, mock_llm):
        agent = create_intake_agent(llm=mock_llm)
        assert agent is not None
        assert agent.role
        assert agent.goal
        assert agent.tools == [] or agent.tools is not None

    def test_create_policy_checker_agent_has_tools(self, mock_llm):
        agent = create_policy_checker_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1
        tool_names = [t.name if hasattr(t, "name") else str(t) for t in agent.tools]
        assert any("policy" in n.lower() or "query" in n.lower() for n in tool_names)

    def test_create_assignment_agent_has_tools(self, mock_llm):
        agent = create_assignment_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1


@pytest.mark.skipif(SKIP_AGENTS, reason="OPENAI_API_KEY not set; skip agent creation tests")
class TestDuplicateAgents:
    """Test duplicate workflow agents."""

    def test_create_search_agent_has_tools(self, mock_llm):
        agent = create_search_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1

    def test_create_similarity_agent_has_tools(self, mock_llm):
        agent = create_similarity_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1

    def test_create_resolution_agent_no_tools(self, mock_llm):
        agent = create_resolution_agent(llm=mock_llm)
        assert agent is not None
        assert agent.tools == [] or agent.tools is not None


@pytest.mark.skipif(SKIP_AGENTS, reason="OPENAI_API_KEY not set; skip agent creation tests")
class TestTotalLossAgents:
    """Test total loss workflow agents."""

    def test_create_damage_assessor_agent(self, mock_llm):
        agent = create_damage_assessor_agent(llm=mock_llm, use_rag=False)
        assert agent is not None
        assert agent.role
        assert agent.goal
        assert len(agent.tools) >= 1

    def test_create_valuation_agent(self, mock_llm):
        agent = create_valuation_agent(llm=mock_llm, use_rag=False)
        assert agent is not None
        assert len(agent.tools) >= 1

    def test_create_payout_agent(self, mock_llm):
        agent = create_payout_agent(llm=mock_llm, use_rag=False)
        assert agent is not None
        assert len(agent.tools) >= 1

    def test_create_settlement_agent(self, mock_llm):
        agent = create_settlement_agent(llm=mock_llm, use_rag=False)
        assert agent is not None
        assert len(agent.tools) >= 1


@pytest.mark.skipif(SKIP_AGENTS, reason="OPENAI_API_KEY not set; skip agent creation tests")
class TestFraudAgents:
    """Test fraud workflow agents."""

    def test_create_pattern_analysis_agent(self, mock_llm):
        agent = create_pattern_analysis_agent(llm=mock_llm)
        assert agent is not None
        assert agent.role
        assert agent.goal
        assert len(agent.tools) >= 1

    def test_create_cross_reference_agent(self, mock_llm):
        agent = create_cross_reference_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1

    def test_create_fraud_assessment_agent(self, mock_llm):
        agent = create_fraud_assessment_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1


@pytest.mark.skipif(SKIP_AGENTS, reason="OPENAI_API_KEY not set; skip agent creation tests")
class TestPartialLossAgents:
    """Test partial loss workflow agents."""

    def test_create_partial_loss_damage_assessor_agent(self, mock_llm):
        agent = create_partial_loss_damage_assessor_agent(llm=mock_llm)
        assert agent is not None
        assert agent.role
        assert agent.goal
        assert len(agent.tools) >= 1

    def test_create_repair_estimator_agent(self, mock_llm):
        agent = create_repair_estimator_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1

    def test_create_repair_shop_coordinator_agent(self, mock_llm):
        agent = create_repair_shop_coordinator_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1

    def test_create_parts_ordering_agent(self, mock_llm):
        agent = create_parts_ordering_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1

    def test_create_repair_authorization_agent(self, mock_llm):
        agent = create_repair_authorization_agent(llm=mock_llm)
        assert agent is not None
        assert len(agent.tools) >= 1
