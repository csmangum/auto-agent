"""Policyholder dispute workflow crew.

This crew handles disputes on existing claims through:
1. Intake — retrieve original claim data and classify the dispute
2. Policy & compliance analysis — review applicable policy terms and regulations
3. Resolution — auto-resolve (valuation/repair/deductible) or escalate (liability)
"""

from claim_agent.agents.dispute import (
    create_dispute_intake_agent,
    create_dispute_policy_analyst_agent,
    create_dispute_resolution_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_dispute_crew(llm: LLMProtocol | None = None, state: str = "California"):
    """Create the Dispute crew: intake -> policy analysis -> resolution.

    Returns:
        Crew configured for policyholder dispute handling.
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_dispute_intake_agent),
            AgentConfig(create_dispute_policy_analyst_agent),
            AgentConfig(create_dispute_resolution_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

DISPUTE DATA (JSON):
{dispute_data}

You are handling a policyholder dispute on an existing claim.

Steps:
1. Use lookup_original_claim with the claim_id from the dispute data to retrieve the
   original claim record, workflow results, and settlement details.
2. Use classify_dispute with the claim data JSON, the dispute_description from dispute
   data, and the dispute_type from dispute data as the type hint.
3. Summarize:
   - The original claim outcome (status, claim_type, payout_amount)
   - The dispute classification (type, auto_resolvable)
   - The policyholder's position and any evidence provided
   - Relevant policy number and vehicle details

Output the intake summary for the policy analyst.""",
                expected_output=(
                    "Intake summary with original claim details, dispute classification "
                    "(type and auto_resolvable), policyholder position, and policy reference."
                ),
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

DISPUTE DATA (JSON):
{dispute_data}

Using the intake summary from the previous task, review the policy and compliance
requirements for this dispute.

Steps:
1. Use query_policy_db with the policy_number from the claim to retrieve policy terms.
2. Use search_policy_compliance to find regulations relevant to the dispute type:
   - For valuation disputes: search "appraisal rights" and "actual cash value"
   - For repair estimate disputes: search "OEM parts" and "labor rate disputes"
   - For deductible disputes: search "deductible" and "undisputed amounts"
   - For liability disputes: search "arbitration" and "liability determination"
3. Use get_compliance_deadlines to identify time-sensitive obligations.
4. Use get_required_disclosures to find mandatory policyholder notifications.

Output the compliance analysis including:
- Applicable regulations with references
- Required disclosures for the policyholder
- Compliance deadlines
- Policyholder rights (appraisal, arbitration, DOI complaint)
- Relevant policy provisions""",
                expected_output=(
                    "Compliance analysis with applicable regulations, required disclosures, "
                    "deadlines, policyholder rights, and relevant policy provisions."
                ),
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

DISPUTE DATA (JSON):
{dispute_data}

ORIGINAL WORKFLOW OUTPUT:
{original_workflow_output}

Using the intake summary and compliance analysis from previous tasks, resolve this dispute.

If the dispute is AUTO-RESOLVABLE (valuation_disagreement, repair_estimate, or
deductible_application):
1. Re-run the relevant calculation:
   - Valuation: use fetch_vehicle_value with VIN, year, make, model from the claim
   - Repair estimate: use calculate_repair_estimate with the claim data
   - Deductible/payout: use calculate_payout with VIN, year, make, model, estimated_damage
2. Compare the recalculated amount against the original
3. Determine if an adjustment is warranted based on the policyholder's evidence
   and policy provisions from the compliance analysis
4. Use generate_dispute_report with:
   - claim_id, dispute_type, resolution_type="auto_resolved"
   - findings summarizing the analysis
   - original_amount and adjusted_amount (if changed)
   - compliance_notes from the policy analysis
   - recommended_action for next steps

If the dispute requires ESCALATION (liability_determination or complex cases):
1. Compile all findings from intake and policy analysis
2. Document the policyholder's position and evidence
3. Note applicable arbitration/appraisal rights from compliance analysis
4. Use escalate_claim to flag for human adjuster review
5. Use generate_dispute_report with:
   - claim_id, dispute_type, resolution_type="escalated"
   - findings summarizing what was reviewed
   - escalation_reasons explaining why human review is needed
   - recommended_action for the adjuster
   - compliance_notes and policyholder_rights

Output the final dispute resolution report.""",
                expected_output=(
                    "Dispute resolution report with resolution_type (auto_resolved or escalated), "
                    "findings, amounts (original and adjusted if applicable), compliance notes, "
                    "and recommended next steps."
                ),
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
        agent_kwargs={"state": state},
    )
