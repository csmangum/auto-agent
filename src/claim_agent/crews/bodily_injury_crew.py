"""Bodily injury workflow crew for injury-related claims."""

from claim_agent.agents.bodily_injury import (
    create_bi_intake_specialist_agent,
    create_medical_records_reviewer_agent,
    create_settlement_negotiator_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew
from claim_agent.models.workflow_output import BIWorkflowOutput


def create_bodily_injury_crew(llm: LLMProtocol | None = None):
    """Create the Bodily Injury crew: intake injury details → review medical records → assess liability → propose settlement.

    Known limitation: Claims with both property damage and injury are routed to
    a single crew (BI if injury is significant). Vehicle damage is not handled
    by this crew; consider a combined or two-phase workflow for such claims.

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
3. Use add_claim_note with:
   - claim_id from claim_data
   - actor_id: "BI Intake Specialist"
   - note: the injury intake summary including:
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

Review medical records, audit bills, build treatment timeline, and assess injury severity.

1. Use query_medical_records with claim_id from claim_data (do not generate or invent a claim_id; it will always be present).
2. Use build_treatment_timeline with medical_records_json and incident_date from claim_data. Treatment duration affects settlement value.
3. Use audit_medical_bills with medical_records_json to check for duplicates, excessive treatment, unrelated conditions. Use total_allowed (not total_billed) for settlement if audit reduces amount.
4. Use assess_injury_severity with:
   - injury_description from the intake summary (or incident_description/damage_description from claim_data)
   - medical_records_json: the JSON output from query_medical_records
5. Document the medical review: total_medical_charges (post-audit), severity, treatment_duration_days, audit_findings, recommended_range_low, recommended_range_high.
6. Use add_claim_note with claim_id, actor_id "Medical Records Reviewer", and the medical review findings.

Output the medical review summary with total_medical_charges, severity, treatment_duration_days, audit_reduction (if any), recommended_range_low, recommended_range_high, treatment_summary.""",
                expected_output="Medical review with total_medical_charges (post-audit), severity, treatment_duration_days, audit_findings, recommended_range_low, recommended_range_high, treatment_summary.",
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

INTAKE AND MEDICAL REVIEW (from previous tasks):
Use injury_description, total_medical_charges (post-audit), severity from prior tasks.

Assess liability exposure, check prerequisites, and propose settlement.

1. Extract claim_id, policy_number, loss_state from claim_data.
2. Use check_pip_medpay_exhaustion with claim_id, policy_number, medical_charges, loss_state. If bi_settlement_allowed is false, escalate_claim (PIP not exhausted).
3. If wage loss is indicated in claim_data (e.g., "missed work", "lost wages"), use calculate_loss_of_earnings with pre_accident_income and days_missed first; pass recommended_amount as loss_of_earnings into calculate_bi_settlement (otherwise 0).
4. Use calculate_bi_settlement with claim_id, policy_number, medical_charges, injury_severity, pain_suffering_multiplier (1.5 moderate; 1.0 minor; 2.0+ severe), and loss_of_earnings from step 3.
5. Use check_cms_reporting_required with claim_id, settlement_amount (proposed_settlement from calculate_bi_settlement), claimant_medicare_eligible (infer from claimant age 65+ or claim data). Document if reporting_required.
6. Use check_minor_settlement_approval with claim_id, claimant_age (if known), claimant_incapacitated, loss_state, court_approval_obtained from claim_data if documented. If court_approval_required and not obtained, note payout must wait for court order; set minor_court_approval_obtained in output.
7. If proposed settlement >= $100,000, use get_structured_settlement_option with claim_id and total_settlement. Offer structured option when recommended.
8. Use add_claim_note with claim_id, actor_id "Settlement Negotiator", and settlement rationale including PIP status, CMS reporting, minor approval, structured option.

Return structured output: payout_amount, medical_charges, pain_suffering, injury_severity, loss_of_earnings (if any), pip_medpay_exhausted, cms_reporting_required, minor_court_approval_required, minor_court_approval_obtained, structured_settlement_offered, policy_bi_limit_per_person, policy_bi_limit_per_accident.""",
                expected_output="Structured settlement proposal with payout_amount, medical_charges, pain_suffering, injury_severity, loss_of_earnings, pip_medpay_exhausted, cms_reporting_required, minor_court_approval_required, minor_court_approval_obtained, structured_settlement_offered, policy limits.",
                agent_index=2,
                context_task_indices=[0, 1],
                output_pydantic=BIWorkflowOutput,
            ),
        ],
        llm=llm,
    )
