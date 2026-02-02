"""Partial loss workflow crew for repairable vehicle damage."""

from crewai import Crew, Task

from claim_agent.agents.partial_loss import (
    create_partial_loss_damage_assessor_agent,
    create_repair_estimator_agent,
    create_repair_shop_coordinator_agent,
    create_parts_ordering_agent,
    create_repair_authorization_agent,
)
from claim_agent.config.llm import get_llm
from claim_agent.config.settings import get_crew_verbose


def create_partial_loss_crew(llm=None):
    """Create the Partial Loss crew: damage assess -> estimate -> shop assignment -> parts order -> authorization.
    
    This crew handles repairable vehicle damage claims:
    1. Assess damage and confirm it's repairable (not total loss)
    2. Calculate repair estimate with parts and labor
    3. Find and assign a repair shop
    4. Order required parts
    5. Generate repair authorization and close claim
    """
    llm = llm or get_llm()
    
    # Create agents
    damage_assessor = create_partial_loss_damage_assessor_agent(llm)
    repair_estimator = create_repair_estimator_agent(llm)
    shop_coordinator = create_repair_shop_coordinator_agent(llm)
    parts_ordering = create_parts_ordering_agent(llm)
    authorization_agent = create_repair_authorization_agent(llm)

    # Task 1: Assess damage (claim_data injected so agent can pass it to tools)
    assess_damage_task = Task(
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
        agent=damage_assessor,
    )

    # Task 2: Calculate repair estimate
    estimate_task = Task(
        description="""Calculate a complete repair estimate using calculate_repair_estimate tool.
Pass: damage_description, vehicle_make, vehicle_year, policy_number from claim_data.

The estimate should include:
- Parts needed with costs
- Labor hours and cost
- Total repair cost
- Deductible from policy
- Amount customer pays vs insurance pays

Use get_parts_catalog if you need more details on specific parts.""",
        expected_output="Complete repair estimate with parts list, labor hours, total cost, deductible, customer responsibility, and insurance payment amount.",
        agent=repair_estimator,
        context=[assess_damage_task],
    )

    # Task 3: Find and assign repair shop
    shop_assignment_task = Task(
        description="""Find available repair shops and assign the best one for this claim.

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
        agent=shop_coordinator,
        context=[assess_damage_task, estimate_task],
    )

    # Task 4: Order parts
    parts_order_task = Task(
        description="""Order all required parts for the repair.

1. Use get_parts_catalog with damage_description and vehicle_make to get recommended parts.
   - Use 'aftermarket' for part_type_preference unless policy specifies OEM

2. Create the parts order using create_parts_order:
   - Include claim_id from claim_data
   - List all parts with part_id, quantity (1 each unless multiple needed), and part_type
   - Include shop_id for delivery

Output the order confirmation with order ID, items, total cost, and delivery date.""",
        expected_output="Parts order confirmation with order_id, list of parts ordered, total parts cost, and estimated delivery date.",
        agent=parts_ordering,
        context=[assess_damage_task, estimate_task, shop_assignment_task],
    )

    # Task 5: Generate authorization and close claim
    authorization_task = Task(
        description="""Generate the repair authorization and finalize the claim.

1. Use generate_repair_authorization with:
   - claim_id from claim_data (or generate one with generate_claim_id if not present)
   - shop_id from the shop assignment
   - Repair estimate amounts: total_estimate, parts_cost, labor_cost, deductible, customer_pays, insurance_pays
   - customer_approved: true

2. Generate the final report using generate_report:
   - claim_id: the claim ID
   - claim_type: 'partial_loss'
   - status: 'approved' 
   - summary: One paragraph summarizing: damage, repair cost, shop assigned, parts ordered, authorization issued
   - payout_amount: the insurance_pays amount

Output the authorization details and claim summary.""",
        expected_output="Repair authorization document with authorization_id, authorized amounts, terms, and final claim report with payout amount.",
        agent=authorization_agent,
        context=[assess_damage_task, estimate_task, shop_assignment_task, parts_order_task],
    )

    return Crew(
        agents=[
            damage_assessor,
            repair_estimator,
            shop_coordinator,
            parts_ordering,
            authorization_agent,
        ],
        tasks=[
            assess_damage_task,
            estimate_task,
            shop_assignment_task,
            parts_order_task,
            authorization_task,
        ],
        verbose=get_crew_verbose(),
    )
