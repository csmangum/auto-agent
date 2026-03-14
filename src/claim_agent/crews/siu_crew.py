"""SIU Investigation crew for claims under Special Investigations Unit review.

Runs when a claim has been escalated to SIU (status: under_investigation) with
an SIU case. Performs document verification, records investigation, and case
management including state fraud bureau filing.
"""

from claim_agent.agents.siu import (
    create_siu_case_manager_agent,
    create_siu_document_verification_agent,
    create_siu_records_investigator_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_siu_crew(llm: LLMProtocol | None = None):
    """Create the SIU Investigation crew: document verification -> records -> case management.

    This crew processes claims under SIU investigation and performs:
    - Document verification: Verify proof of loss, repair estimates, IDs, photos
    - Records investigation: Check prior claims, fraud flags, SIU cases on VIN/policy
    - Case management: Synthesize findings, file state fraud reports, update case status

    Returns:
        Crew configured for SIU investigation workflow.
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_siu_document_verification_agent),
            AgentConfig(create_siu_records_investigator_agent),
            AgentConfig(create_siu_case_manager_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""SIU CASE CONTEXT:
{claim_data}

You are the SIU Document Verification Specialist. The claim has been referred to SIU for investigation.

Steps:
1. Use get_siu_case_details with the siu_case_id from claim_data to retrieve case context.
2. Verify key documents: proof_of_loss, repair_estimate, and photos using verify_document_authenticity.
3. Add investigation notes with add_siu_investigation_note (category: document_review) for each verification.
4. Document any findings that support or contradict the fraud indicators.

Output a document verification summary: documents checked, verified status, findings, recommendations.""",
                expected_output=(
                    "Document verification summary with documents checked, verified status, "
                    "findings, and recommendations. SIU case notes added for each verification."
                ),
                agent_index=0,
            ),
            TaskConfig(
                description="""SIU CASE CONTEXT:
{claim_data}

You are the SIU Records Investigator. Investigate claimant and vehicle history.

Steps:
1. Use get_siu_case_details with siu_case_id to understand the case and fraud indicators.
2. Use check_claimant_investigation_history with claim_id and VIN from claim_data.
3. Use search_claims_db if additional claims search is needed.
4. Add investigation notes with add_siu_investigation_note (category: records_check) documenting prior claims, fraud flags, SIU cases.
5. Assess whether history supports or contradicts the fraud referral.

Output an investigation summary: prior_claims, prior_fraud_flags, prior_siu_cases, risk_summary, pattern_analysis.""",
                expected_output=(
                    "Records investigation summary with prior_claims, prior_fraud_flags, "
                    "prior_siu_cases, risk_summary. SIU case notes added for findings."
                ),
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""SIU CASE CONTEXT:
{claim_data}

You are the SIU Case Manager. Synthesize findings and produce the investigation outcome.

Steps:
1. Use get_siu_case_details to review full case and prior agent findings.
2. Use get_fraud_detection_guidance to check state SIU reporting requirements (use state from claim_data or default California).
3. Synthesize document verification and records investigation into a findings summary.
4. Determine outcome: closed (no fraud), closed (fraud confirmed), or referred.
5. If fraud confirmed or referred: use file_fraud_report_state_bureau with claim_id, case_id, state, and indicators.
6. Use update_siu_case_status to set final status (closed or referred).
7. Use add_siu_investigation_note (category: findings) with your recommendation.
8. Use add_claim_note to add the final SIU recommendation to the claim for adjusters.

Output the final investigation report: case_id, claim_id, findings_summary, recommendation, state_report_filed, case_status.""",
                expected_output=(
                    "Final SIU investigation report with findings_summary, recommendation, "
                    "state_report_filed (if applicable), case_status. Case status updated. "
                    "Claim note added with recommendation."
                ),
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
    )
