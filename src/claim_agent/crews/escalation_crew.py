"""Escalation (HITL) crew: evaluates claims for human review.

The main pipeline uses evaluate_escalation_impl (in tools.logic) directly for
deterministic escalation. This crew is for optional or manual use (e.g. narrative
reports, agent-driven evaluation).
"""

from claim_agent.agents.escalation import create_escalation_agent
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_escalation_crew(llm: LLMProtocol | None = None):
    """Create the Escalation crew: single agent evaluates claim for escalation (optional/manual use)."""
    return create_crew(
        agents_config=[AgentConfig(create_escalation_agent)],
        tasks_config=[
            TaskConfig(
                description="""You are given claim_data (JSON) and router_output (the router's classification text).

CLAIM DATA (JSON):
{claim_data}

ROUTER OUTPUT:
{router_output}

Evaluate whether this claim needs human review by:
1. Using the evaluate_escalation tool with claim_data and router_output. Pass empty strings for similarity_score and payout_amount if not available.
2. If the tool returns needs_review true, use detect_fraud_indicators on claim_data to list any fraud indicators.
3. Use generate_escalation_report to produce a final report with claim_id, needs_review, escalation_reasons, priority, recommended_action, and fraud_indicators.

Output: the escalation report (needs_review yes/no, reasons, priority, recommended action).""",
                expected_output="Escalation report: needs_review (yes/no), escalation_reasons, priority (low/medium/high/critical), recommended_action, and fraud_indicators if any.",
                agent_index=0,
            ),
        ],
        llm=llm,
    )
