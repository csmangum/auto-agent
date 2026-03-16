"""Liability determination crew: structured fault analysis before settlement."""

from claim_agent.agents.liability import create_liability_analyst_agent
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
from claim_agent.models.claim import LiabilityDeterminationOutput


def create_liability_determination_crew(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the liability determination crew for pre-settlement fault analysis."""
    return create_crew(
        agents_config=[
            AgentConfig(create_liability_analyst_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT:
{workflow_output}

Determine liability for this claim. Use loss_state from claim_data (default California if absent) for state-specific rules.

1. Use assess_liability with incident_description from claim_data and workflow_output for context.
2. Use get_comparative_fault_rules_tool with state=loss_state to get comparative fault rules.
3. Use search_state_compliance with query "comparative fault" or "liability" and state=loss_state for additional context.

Apply state rules:
- pure_comparative (CA, NY): insured can recover even when partially or mostly at fault; recovery is reduced by fault %; set recovery_eligible=True unless other legal/coverage factors bar recovery
- modified_comparative_51 (TX, FL): no recovery if insured >= 51% at fault; recovery_eligible only if liability_percentage < 51
- contributory: recovery_eligible only if liability_percentage is 0

Produce structured output with:
- liability_percentage: 0-100 (insured's share of fault; 0=not at fault, 100=fully at fault; None if unclear)
- liability_basis: brief reasoning/source
- fault_determination: at_fault | not_at_fault | unclear
- third_party_identified: bool
- recovery_eligible: bool (per state rules)""",
                expected_output="Structured liability determination with liability_percentage, liability_basis, fault_determination, third_party_identified, recovery_eligible.",
                agent_index=0,
                output_pydantic=LiabilityDeterminationOutput,
            ),
        ],
        llm=llm,
        agent_kwargs={"state": state, "use_rag": use_rag},
    )
