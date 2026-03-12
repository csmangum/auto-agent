"""Escalation (HITL) crew: agent evaluates claims for human review using rule evidence."""

from claim_agent.agents.escalation import create_escalation_agent
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
from claim_agent.models.stage_outputs import EscalationCheckResult


def create_escalation_crew(llm: LLMProtocol | None = None):
    """Create the Escalation crew: single agent uses evidence to decide escalation."""
    return create_crew(
        agents_config=[AgentConfig(create_escalation_agent)],
        tasks_config=[
            TaskConfig(
                description="""You are given claim_data (JSON), router_output, and optional similarity_score, payout_amount, router_confidence.

CLAIM DATA (JSON):
{claim_data}

ROUTER OUTPUT:
{router_output}

SIMILARITY_SCORE (optional, 0-100): {similarity_score}
PAYOUT_AMOUNT (optional): {payout_amount}
ROUTER_CONFIDENCE (optional, 0-1): {router_confidence}

Your job is to decide whether this claim needs human review. Do NOT delegate the decision to a tool.

1. Call get_escalation_evidence with claim_data, router_output, similarity_score, payout_amount, and router_confidence. This returns rule outputs (fraud_indicators, description_overlap score/threshold, router_confidence, high_value, etc.) as EVIDENCE only.

2. Review the evidence. Consider:
   - fraud_indicators: rule-detected codes (e.g. incident_damage_description_mismatch). Low overlap alone may be a false positive if incident and damage are semantically consistent (e.g. "rear-ended" vs "rear bumper dented").
   - description_overlap: if present, score vs threshold. Use your judgment: does the evidence suggest a real mismatch or just lexical difference?
   - router_confidence vs confidence_threshold
   - high_value, ambiguous_similarity

3. Decide: needs_review (bool), escalation_reasons (list), priority (low/medium/high/critical), recommended_action (str), fraud_indicators (list — include only indicators you agree warrant escalation).

Output your decision in the required structured format.""",
                expected_output="EscalationCheckResult: needs_review, escalation_reasons, priority, recommended_action, fraud_indicators.",
                agent_index=0,
                output_pydantic=EscalationCheckResult,
            ),
        ],
        llm=llm,
    )
