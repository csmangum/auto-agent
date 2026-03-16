"""Supplemental claim workflow crew.

Handles additional damage discovered during repair (common in partial loss).
Flow: Validate supplemental -> Compare to original -> Adjust estimate -> Update authorization.
"""

from claim_agent.agents.supplemental import (
    create_damage_verifier_agent,
    create_estimate_adjuster_agent,
    create_supplemental_intake_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_supplemental_crew(llm: LLMProtocol | None = None, state: str = "California"):
    """Create the Supplemental crew: intake -> verify damage -> adjust estimate -> update authorization.

    Handles supplemental damage reports on existing partial loss claims:
    1. Validate supplemental report and retrieve original estimate
    2. Compare supplemental damage to original scope
    3. Calculate supplemental estimate and update authorization
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_supplemental_intake_agent),
            AgentConfig(create_damage_verifier_agent),
            AgentConfig(create_estimate_adjuster_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

SUPPLEMENTAL DATA (JSON):
{supplemental_data}

You are handling a supplemental damage report on an existing partial loss claim.
Additional damage was discovered during repair.

Steps:
1. Use get_original_repair_estimate with claim_id from claim_data to retrieve
   the original repair estimate and authorization.
2. Verify the claim has a completed partial loss workflow (no error in response).
3. Extract original total_estimate, parts_cost, labor_cost, shop_id, authorization_id.
4. Validate the supplemental_damage_description is specific enough.
5. Use query_policy_db to verify policy coverage.
6. Use get_repair_standards to check supplemental authorization requirements (California CCR 2695.8).

Output an intake summary with original estimate, authorization details, and supplemental damage description.""",
                expected_output=(
                    "Intake summary with original total_estimate, parts_cost, labor_cost, "
                    "shop_id, authorization_id, and supplemental_damage_description."
                ),
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

SUPPLEMENTAL DATA (JSON):
{supplemental_data}

ORIGINAL WORKFLOW OUTPUT:
{original_workflow_output}

Using the intake summary from the previous task, verify the supplemental damage is genuinely additional.

Steps:
1. Compare supplemental_damage_description to the original damage scope.
2. Verify the supplemental damage could not have been identified during initial assessment
   (e.g., hidden frame damage discovered when bumper was removed).
3. Use evaluate_damage with the supplemental_damage_description to assess severity.
4. Flag any overlap with original estimate (duplicate components).
5. Determine: proceed_with_supplemental or flag_for_review.

Output verification summary with is_additional and recommendation.""",
                expected_output=(
                    "Verification summary with original_scope, supplemental_scope, "
                    "is_additional (true/false), and recommendation."
                ),
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

SUPPLEMENTAL DATA (JSON):
{supplemental_data}

ORIGINAL WORKFLOW OUTPUT:
{original_workflow_output}

Using the intake and verification from previous tasks, calculate the supplemental estimate and update the authorization.

Steps:
1. Use calculate_supplemental_estimate with:
   - supplemental_damage_description from supplemental_data
   - vehicle_make, vehicle_year, policy_number from claim_data
   - shop_id from the original estimate (from intake/workflow output)
   - loss_state from claim_data when available (for state-specific total loss threshold)
2. Extract supplemental total_estimate, parts_cost, labor_cost, insurance_pays.
3. Use update_repair_authorization with:
   - claim_id, shop_id from claim_data/original
   - original_total, original_parts, original_labor, original_insurance_pays from original estimate
   - supplemental_total, supplemental_parts, supplemental_labor, supplemental_insurance_pays
   - authorization_id from original if available
4. Return the combined totals and supplemental_authorization_id.

Output structured result: supplemental_estimate, combined_total, supplemental_authorization_id, combined_insurance_pays.""",
                expected_output=(
                    "Structured output with supplemental_estimate, combined_total, "
                    "supplemental_authorization_id, combined_insurance_pays."
                ),
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
        agent_kwargs={"state": state},
    )
