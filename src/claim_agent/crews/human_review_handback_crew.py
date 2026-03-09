"""Human review handback crew: processes claims returned from human review with a decision.

Flow: Parse reviewer decision → Update claim → Route to next step (settlement, denial, subrogation)
Integration: Post-escalation; handles needs_review → processing transitions.
"""

from claim_agent.agents.human_review_handback import create_handback_agent
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_human_review_handback_crew(llm=None):
    """Create the Human Review Handback crew."""
    return create_crew(
        agents_config=[AgentConfig(create_handback_agent)],
        tasks_config=[
            TaskConfig(
                description="""You are processing a claim returned from human review with an approval decision.

CLAIM ID: {claim_id}

REVIEWER DECISION (optional structured input):
{reviewer_decision}

ACTOR ID (for audit trail): {actor_id}

1. Use get_escalation_context with claim_id to retrieve why the claim was escalated and the prior workflow context.
2. Use parse_reviewer_decision with reviewer_decision (or empty string if not provided) to extract confirmed_claim_type and confirmed_payout.
3. Use apply_reviewer_decision to update the claim with any confirmed values. Pass actor_id={actor_id} for the audit trail. Pass confirmed_claim_type and confirmed_payout when the reviewer has explicitly confirmed or overridden them. If the reviewer approved as-is, you may pass empty strings to keep existing values, but you MUST still call apply_reviewer_decision to transition the claim to processing.
4. Output a handback summary: claim_id, applied_claim_type, applied_payout, next_step (workflow, settlement, or subrogation based on claim type), and brief reasoning.""",
                expected_output="Handback summary with claim_id, applied_claim_type, applied_payout, next_step, and reasoning.",
                agent_index=0,
            ),
        ],
        llm=llm,
    )
