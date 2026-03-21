"""Total loss workflow crew.

This crew handles total loss claims with RAG-enriched agents that have
access to relevant policy language and compliance regulations.
"""

from claim_agent.agents.total_loss import (
    create_damage_assessor_agent,
    create_payout_agent,
    create_valuation_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
from claim_agent.models.workflow_output import TotalLossWorkflowOutput


def create_total_loss_crew(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the Total Loss Evaluator crew: assess damage -> valuation -> payout.

    Args:
        llm: Language model to use (defaults to configured LLM)
        state: State jurisdiction for policy/compliance context
        use_rag: Whether to enrich agents with RAG context

    Returns:
        Crew configured for total loss claim processing
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_damage_assessor_agent),
            AgentConfig(create_valuation_agent),
            AgentConfig(create_payout_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Evaluate the damage_description and optional estimated_damage from the claim_data above.
Use the evaluate_damage tool. If the description suggests total loss (e.g. totaled, flood, fire, frame damage) or repair cost would exceed 75% of value, mark as total loss candidate.""",
                expected_output="Damage severity, estimated_repair_cost if any, and total_loss_candidate (true/false).",
                agent_index=0,
            ),
            TaskConfig(
                description="""Fetch the current market value for the vehicle using fetch_vehicle_value.
Use vin, vehicle_year, vehicle_make, vehicle_model from the claim_data.
If comparables are returned, include them for the payout step.
Use loss_state from claim_data for state-specific valuation requirements.""",
                expected_output="Vehicle value in dollars, condition, source, and comparables if available.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""If total loss: calculate payout using the calculate_payout tool.
Pass vehicle value from the valuation step and policy_number from claim_data.
Use loss_state from claim_data when available for tax/title/fees (required in many states).
If loan_balance or similar is present on the claim, pass loan_balance to calculate_payout and claim_id (and vin if available) so gap insurance coordination runs when the policy includes gap coverage.
If the policyholder may retain salvage, call get_salvage_value with vin, vehicle_year, vehicle_make, vehicle_model, damage_description, and vehicle_value from claim_data or valuation. Then call calculate_payout with owner_retain_salvage=True and salvage_value from get_salvage_value.
Use get_total_loss_requirements(state=loss_state) for state-specific requirements.
When loss_state is Georgia (or diminished value applies), call calculate_diminished_value with vehicle_value, mileage and estimated_damage or repair estimate as repair_cost when available, and optional damage_severity_tier (cosmetic, moderate, structural, severe) if itemized repairs are unknown; include diminished_value in total_loss_details when returned.
Return TotalLossWorkflowOutput with payout_amount, vehicle_value, deductible, calculation, and total_loss_details (acv_base, tax_title_fees, acv_total, salvage_deduction, owner_retain_option, comparable_vehicles from valuation if available, diminished_value if computed).""",
                expected_output="Structured output: payout_amount, vehicle_value, deductible, calculation, total_loss_details (ACV breakdown, tax/fees, salvage deduction, owner-retain option).",
Return TotalLossWorkflowOutput with payout_amount, vehicle_value, deductible, calculation, and total_loss_details (acv_base, tax_title_fees, acv_total, salvage_deduction, owner_retain_option, comparable_vehicles from valuation if available, plus gap_claim_id, gap_claim_status, gap_shortfall_amount, gap_approved_amount, gap_remaining_shortfall, gap_denial_reason when gap coordination applies).""",
                expected_output="Structured output: payout_amount, vehicle_value, deductible, calculation, total_loss_details (ACV breakdown, tax/fees, salvage, owner-retain, comparables, gap fields if applicable).",
                agent_index=2,
                context_task_indices=[0, 1],
                output_pydantic=TotalLossWorkflowOutput,
            ),
        ],
        llm=llm,
        agent_kwargs={"state": state, "use_rag": use_rag},
    )
