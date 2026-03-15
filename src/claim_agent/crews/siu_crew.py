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

Verify claim documents (proof of loss, repair estimates, IDs, photos). Use siu_case_id from claim_data. Document findings in SIU case notes (category: document_review). If a tool returns error JSON (tool_failure), document it in your notes and continue with available information. Output: documents checked, verified status, findings, recommendations.""",
                expected_output=(
                    "Document verification summary with documents checked, verified status, "
                    "findings, and recommendations. SIU case notes added for each verification."
                ),
                agent_index=0,
            ),
            TaskConfig(
                description="""SIU CASE CONTEXT:
{claim_data}

Investigate claimant and vehicle history for prior fraud involvement. Use claim_id and VIN from claim_data. Document in SIU case notes (category: records_check). If prior agent had tool failures, note that and proceed with available context. If a tool returns error JSON (tool_failure), document it and continue. Output: prior_claims, prior_fraud_flags, prior_siu_cases, risk_summary, pattern_analysis.""",
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

Synthesize findings and produce investigation outcome. Determine outcome: closed (no fraud), closed (fraud confirmed), or referred. File state fraud report when required; update case status; add claim note with recommendation. If prior agents had tool failures, include that in findings_summary so adjusters are informed. Output: findings_summary, recommendation, state_report_filed, case_status.""",
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
