"""Subrogation recovery crew: assess fault, build case, send demand, track recovery."""

from claim_agent.agents.subrogation import (
    create_demand_specialist_agent,
    create_liability_investigator_agent,
    create_recovery_tracker_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_subrogation_crew(
    llm: LLMProtocol | None = None,
    state: str = "California",
    use_rag: bool = True,
):
    """Create the subrogation crew for recovering payments from at-fault parties."""
    return create_crew(
        agents_config=[
            AgentConfig(create_liability_investigator_agent),
            AgentConfig(create_demand_specialist_agent),
            AgentConfig(create_recovery_tracker_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

WORKFLOW OUTPUT (includes settlement):
{workflow_output}

Assess liability for subrogation. Use assess_liability with the incident_description from claim_data
and workflow_output for context. Determine whether the insured was at-fault or not-at-fault,
and whether a third party can be identified.

If not-at-fault and third party identified: subrogation is recommended.
If at-fault or unclear: document that no subrogation opportunity exists.

Output your liability assessment with fault_determination, third_party_identified, and reasoning.""",
                expected_output="Liability assessment with fault determination and subrogation eligibility.",
                agent_index=0,
            ),
            TaskConfig(
                description="""Using the liability assessment from the previous task:

If the claim is NOT subrogation-eligible (at-fault or unclear): document that no subrogation case
will be built and produce a brief no-subrogation summary.

If the claim IS subrogation-eligible (not-at-fault): use build_subrogation_case with claim_id,
payout_amount from claim_data, and the liability assessment JSON.

Output the subrogation case details (case_id, amount_sought, third_party_info).""",
                expected_output="Subrogation case built (if eligible) or no-subrogation summary.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""Using the subrogation case from the previous task:

If a case was built: use send_demand_letter with case_id, claim_id, and amount_sought.
Use generate_report to document the demand letter status.

If no case was built: document that no demand was sent.""",
                expected_output="Demand letter sent (if eligible) and status documented.",
                agent_index=1,
                context_task_indices=[0, 1],
            ),
            TaskConfig(
                description="""Using the subrogation case and demand context from previous tasks:

Use record_recovery with claim_id and case_id (or N/A if no case). Set recovery_status to 'pending'
(demand sent, awaiting response). Document next steps for follow-up (e.g., arbitration, litigation).

Use generate_report to document the recovery tracking status and next steps.""",
                expected_output="Recovery status recorded and next steps documented.",
                agent_index=2,
                context_task_indices=[0, 1, 2],
            ),
        ],
        llm=llm,
        agent_kwargs={"state": state, "use_rag": use_rag},
    )
