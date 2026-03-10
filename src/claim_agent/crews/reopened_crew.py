"""Reopened claim workflow crew.

Reopens settled claims (e.g., new damage, policyholder appeal).
Flow: Validate reopening reason → Load prior claim → Route to appropriate crew.
"""

from claim_agent.agents.reopened import (
    create_prior_claim_loader_agent,
    create_reopened_router_agent,
    create_reopened_validator_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
from claim_agent.models.workflow_output import ReopenedWorkflowOutput


def create_reopened_crew(llm: LLMProtocol | None = None):
    """Create the Reopened crew: validate reason → load prior claim → route to crew.

    Handles reopened settled claims:
    1. Validate the reopening reason (new damage, policyholder appeal, etc.)
    2. Load the prior claim using prior_claim_id from claim_data
    3. Route to partial_loss, total_loss, or bodily_injury based on prior + new damage
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_reopened_validator_agent),
            AgentConfig(create_prior_claim_loader_agent),
            AgentConfig(create_reopened_router_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

This is a REOPENED claim. The claim_data includes prior_claim_id and/or reopening_reason.

Validate the reopening reason before proceeding:
1. Use query_policy_db to verify the policy allows reopenings and check any time limits.
2. Check that reopening_reason or incident_description indicates a valid reason:
   - new_damage: Additional damage discovered after settlement (e.g., hidden frame damage)
   - policyholder_appeal: Policyholder appealing the original settlement
   - additional_covered_damage: Discovery of additional covered damage
   - regulatory_requirement: Regulatory requirement to reassess
3. Use get_claim_notes with prior_claim_id if available to review context.
4. Output: reopening_reason_validated (true/false), validated_reason (string), and any flags for review.

If the reason is invalid, still output the validation result; the router may escalate.""",
                expected_output=(
                    "Validation summary: reopening_reason_validated (true/false), "
                    "validated_reason, and any policy or compliance notes."
                ),
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Using the validation from the previous task (in your context), load the prior settled claim.

1. Extract prior_claim_id from claim_data. It may be in claim_data.prior_claim_id or claim_data.claim_id if this is a re-run.
2. Use lookup_original_claim(prior_claim_id) to retrieve the prior claim.
3. Extract: claim_type, status, damage_description, payout_amount, incident_description.
4. Verify the prior claim status is settled (or similar closed state).
5. Produce a concise prior_claim_summary for the routing agent.

If prior_claim_id is missing or the claim is not found, output an error summary.""",
                expected_output=(
                    "Prior claim summary with claim_type, status, payout_amount, "
                    "damage_description (brief), and prior_claim_id."
                ),
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Using the validation and prior claim summary from previous tasks (in your context), route this reopened claim to the appropriate crew.

1. Consider the prior claim's claim_type (partial_loss, total_loss, bodily_injury).
2. Consider the NEW damage_description and incident_description in the current claim_data.
3. Use evaluate_damage with the damage_description to assess severity if needed.
4. Route to:
   - partial_loss: New damage is repairable (bumper, fender, additional parts, supplemental)
   - total_loss: New damage indicates total loss (totaled, destroyed, flood, fire) OR prior was total_loss with new complications
   - bodily_injury: Reopening involves injury (new injury, policyholder appeal for BI, medical treatment)

Output a structured result with target_claim_type (exactly one of: partial_loss, total_loss, bodily_injury), prior_claim_id, prior_claim_summary, reopening_reason_validated, and reopening_reason.""",
                expected_output=(
                    "Structured output: target_claim_type (partial_loss, total_loss, or bodily_injury), "
                    "prior_claim_id, prior_claim_summary, reopening_reason_validated, reopening_reason."
                ),
                agent_index=2,
                context_task_indices=[0, 1],
                output_pydantic=ReopenedWorkflowOutput,
            ),
        ],
        llm=llm,
    )
