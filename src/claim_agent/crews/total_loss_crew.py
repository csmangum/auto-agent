"""Total loss workflow crew."""

from crewai import Crew, Task

from claim_agent.agents.total_loss import (
    create_damage_assessor_agent,
    create_valuation_agent,
    create_payout_agent,
    create_settlement_agent,
)
from claim_agent.config.llm import get_llm


def create_total_loss_crew(llm=None):
    """Create the Total Loss Evaluator crew: assess damage -> valuation -> payout -> settlement."""
    llm = llm or get_llm()
    damage_agent = create_damage_assessor_agent(llm)
    valuation_agent = create_valuation_agent(llm)
    payout_agent = create_payout_agent(llm)
    settlement_agent = create_settlement_agent(llm)

    assess_task = Task(
        description="""Evaluate the damage_description and optional estimated_damage from the claim_data.
Use the evaluate_damage tool. If the description suggests total loss (e.g. totaled, flood, fire, frame damage) or repair cost would exceed 75% of value, mark as total loss candidate.""",
        expected_output="Damage severity, estimated_repair_cost if any, and total_loss_candidate (true/false).",
        agent=damage_agent,
    )

    valuation_task = Task(
        description="""Fetch the current market value for the vehicle using fetch_vehicle_value.
Use vin, vehicle_year, vehicle_make, vehicle_model from the claim_data.""",
        expected_output="Vehicle value in dollars, condition, and source.",
        agent=valuation_agent,
        context=[assess_task],
    )

    payout_task = Task(
        description="""If total loss: calculate payout using the calculate_payout tool.
Pass vehicle value from the valuation step and the policy_number from claim_data.
The tool will look up the deductible and compute payout (vehicle value minus deductible).
Output the payout amount and calculation details.""",
        expected_output="Payout amount in dollars and one-line calculation (e.g. value - deductible).",
        agent=payout_agent,
        context=[assess_task, valuation_task],
    )

    settlement_task = Task(
        description="""Generate the settlement report and close the claim.
Use generate_report with claim_id (generate one with generate_claim_id if not set), claim_type='total_loss', status='closed', summary (one paragraph of actions and payout), and payout_amount.""",
        expected_output="Settlement report summary and claim closed confirmation with payout amount.",
        agent=settlement_agent,
        context=[assess_task, valuation_task, payout_task],
    )

    return Crew(
        agents=[damage_agent, valuation_agent, payout_agent, settlement_agent],
        tasks=[assess_task, valuation_task, payout_task, settlement_task],
        verbose=True,
    )
