"""Partial loss workflow crew for repairable vehicle damage."""

from claim_agent.agents.partial_loss import (
    create_parts_ordering_agent,
    create_partial_loss_damage_assessor_agent,
    create_repair_authorization_agent,
    create_repair_estimator_agent,
    create_repair_shop_coordinator_agent,
)
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
from claim_agent.models.workflow_output import PartialLossWorkflowOutput


def create_partial_loss_crew(llm=None):
    """Create the Partial Loss crew: damage assess -> estimate -> shop assignment -> parts order -> authorization.

    This crew handles repairable vehicle damage claims:
    1. Assess damage and confirm it's repairable (not total loss)
    2. Calculate repair estimate with parts and labor
    3. Find and assign a repair shop
    4. Order required parts
    5. Generate repair authorization and hand off to the shared settlement crew
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_partial_loss_damage_assessor_agent),
            AgentConfig(create_repair_estimator_agent),
            AgentConfig(create_repair_shop_coordinator_agent),
            AgentConfig(create_parts_ordering_agent),
            AgentConfig(create_repair_authorization_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Evaluate the damage_description from claim_data above to assess the repair scope.
Use the evaluate_damage tool with the damage_description.
Also fetch the vehicle value using fetch_vehicle_value with vin, vehicle_year, vehicle_make, vehicle_model.

Determine:
- Severity of damage (minor, moderate, severe)
- Whether this is repairable or should be reclassified as total loss
- List of damaged components that need repair/replacement

If estimated repair cost would exceed 75% of vehicle value, flag as potential total loss.""",
                expected_output="Damage assessment with severity, list of damaged parts, vehicle value, and confirmation that this is a partial loss (repairable) claim.",
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Calculate a complete repair estimate using calculate_repair_estimate tool.
Extract and use damage_description, vehicle_make, vehicle_year, policy_number from the claim_data JSON above.

The estimate should include:
- Parts needed with costs
- Labor hours and cost
- Total repair cost
- Deductible from policy
- Amount customer pays vs insurance pays

Use get_parts_catalog if you need more details on specific parts.""",
                expected_output="Complete repair estimate with parts list, labor hours, total cost, deductible, customer responsibility, and insurance payment amount.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Find available repair shops and assign the best one for this claim.

1. Use get_available_repair_shops to get a list of available shops.
   - Filter by network_type 'preferred' first for best rates
   - Consider vehicle_make if it's a specialty vehicle (Tesla, BMW, etc.)

2. Select the best shop based on:
   - Highest rating
   - Shortest wait time
   - Appropriate certifications

3. Use assign_repair_shop with claim_id from claim_data and the selected shop_id.
   - Estimate repair days based on damage severity (minor: 3, moderate: 5, severe: 7)

Output the shop assignment details including start and completion dates.""",
                expected_output="Repair shop assignment with shop name, address, phone, confirmation number, estimated start date, and estimated completion date.",
                agent_index=2,
                context_task_indices=[0, 1],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Order all required parts for the repair.

1. Use get_parts_catalog with damage_description and vehicle_make from claim_data to get recommended parts.
   - Use 'aftermarket' for part_type_preference unless policy specifies OEM

2. Create the parts order using create_parts_order:
   - Include claim_id from claim_data
   - List all parts with part_id, quantity (1 each unless multiple needed), and part_type
   - Include shop_id for delivery

Output the order confirmation with order ID, items, total cost, and delivery date.""",
                expected_output="Parts order confirmation with order_id, list of parts ordered, total parts cost, and estimated delivery date.",
                agent_index=3,
                context_task_indices=[0, 1, 2],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Generate the repair authorization and prepare the claim for shared settlement.

1. Use generate_repair_authorization with:
   - claim_id from claim_data (or generate one with generate_claim_id if not present)
   - shop_id from the shop assignment
   - Repair estimate amounts: total_estimate, parts_cost, labor_cost, deductible, customer_pays, insurance_pays
   - customer_approved: true

2. Return a structured output with all fields from the generate_repair_authorization result:
   - payout_amount: the insurance_pays value (amount insurance will pay)
   - authorization_id, claim_id, shop_id, shop_name, shop_phone, authorized_amount, shop_webhook_url
   - total_estimate: total repair estimate from the estimate step

Pass through the full generate_repair_authorization result so the settlement crew and webhooks receive complete data.

Do not generate the final claim report in this crew; that is handled by the shared settlement crew.""",
                expected_output="Structured output: payout_amount, authorization_id, claim_id, shop_id, shop_name, shop_phone, authorized_amount, total_estimate, shop_webhook_url.",
                agent_index=4,
                context_task_indices=[0, 1, 2, 3],
                output_pydantic=PartialLossWorkflowOutput,
            ),
        ],
        llm=llm,
    )
