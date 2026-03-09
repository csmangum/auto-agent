"""Bodily injury workflow crew for injury-related claims."""

from claim_agent.agents.bodily_injury import (
    create_bi_intake_specialist_agent,
    create_medical_records_reviewer_agent,
    create_settlement_negotiator_agent,
)
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
from claim_agent.models.workflow_output import BIWorkflowOutput


def create_bodily_injury_crew(llm=None):
    """Create the Bodily Injury crew: intake injury details → review medical records → assess liability → propose settlement.

    This crew handles injury-related claims:
    1. BI Intake Specialist: Capture injury details and incident description
    2. Medical Records Reviewer: Query medical records, assess injury severity
    3. Settlement Negotiator: Calculate and propose settlement within policy limits
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_bi_intake_specialist_agent),
            AgentConfig(create_medical_records_reviewer_agent),
            AgentConfig(create_settlement_negotiator_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Intake injury-related claim details.

1. Extract and document the incident_description and damage_description from claim_data.
2. Identify any injury-related language (e.g., "injured", "whiplash", "back pain", "broken bone", "hospital").
3. Use add_claim_note to document the injury intake summary including:
   - injury_description: Detailed description of injuries (infer from incident/damage if needed)
   - incident_summary: How the injury occurred
   - claimant_info: Use claim_id or policy_number as identifier
4. If injury details are unclear, note gaps for follow-up.

Output a structured intake summary with injury_description, incident_summary, and any gaps.""",
                expected_output="Intake summary with injury_description, incident_summary, claimant_info, and gaps_or_followups.",
                agent_index=0,
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

INTAKE SUMMARY (from previous task):
Use the injury_description and incident_summary from the intake task.

Review medical records and assess injury severity.

1. Use query_medical_records with claim_id from claim_data (or generate one if missing).
2. Use assess_injury_severity with:
   - injury_description from the intake summary (or incident_description/damage_description from claim_data)
   - medical_records_json: the JSON output from query_medical_records
3. Document the medical review: total_medical_charges, severity, recommended_range_low, recommended_range_high.
4. Use add_claim_note to record findings.

Output the medical review summary with total_medical_charges, severity, recommended_range_low, recommended_range_high, treatment_summary.""",
                expected_output="Medical review with total_medical_charges, severity (minor/moderate/severe/catastrophic), recommended_range_low, recommended_range_high, treatment_summary.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

INTAKE AND MEDICAL REVIEW (from previous tasks):
Use injury_description, total_medical_charges, severity from prior tasks.

Assess liability exposure and propose settlement.

1. Extract claim_id and policy_number from claim_data.
2. Use calculate_bi_settlement with:
   - claim_id from claim_data
   - policy_number from claim_data
   - medical_charges: total_medical_charges from medical review
   - injury_severity: severity from medical review (minor/moderate/severe/catastrophic)
   - pain_suffering_multiplier: 1.5 for moderate; 1.0 for minor; 2.0+ for severe
3. From the calculate_bi_settlement result, extract proposed_settlement as payout_amount.
4. Use add_claim_note to document settlement rationale.

Return a structured output with payout_amount (proposed settlement), medical_charges, pain_suffering, injury_severity, policy_bi_limit.""",
                expected_output="Structured settlement proposal: payout_amount, medical_charges, pain_suffering, injury_severity, policy_bi_limit.",
                agent_index=2,
                context_task_indices=[0, 1],
                output_pydantic=BIWorkflowOutput,
            ),
        ],
        llm=llm,
    )
