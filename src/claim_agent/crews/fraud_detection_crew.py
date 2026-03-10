"""Fraud detection workflow crew.

This crew analyzes claims for potential fraud through:
1. Pattern matching (multiple claims, suspicious timing)
2. Cross-reference with known fraud indicators
3. Comprehensive fraud assessment and recommendation
"""

from claim_agent.agents.fraud import (
    create_cross_reference_agent,
    create_fraud_assessment_agent,
    create_pattern_analysis_agent,
)
from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.crews.factory import AgentConfig, TaskConfig, create_crew


def create_fraud_detection_crew(llm: LLMProtocol | None = None):
    """Create the Fraud Detection crew: pattern analysis -> cross-reference -> assessment.

    This crew processes claims flagged for potential fraud and performs:
    - Pattern analysis: Checks for multiple claims, suspicious timing, staged accident indicators
    - Cross-reference: Matches against known fraud indicators database
    - Assessment: Combines results into fraud likelihood score and recommendations

    Returns:
        Crew configured for fraud detection workflow.
    """
    return create_crew(
        agents_config=[
            AgentConfig(create_pattern_analysis_agent),
            AgentConfig(create_cross_reference_agent),
            AgentConfig(create_fraud_assessment_agent),
        ],
        tasks_config=[
            TaskConfig(
                description="""CLAIM DATA (JSON):
{claim_data}

Analyze the claim for suspicious patterns using the claim_data above.

Steps:
1. Use analyze_claim_patterns with the claim_data JSON to detect patterns.
2. Check for:
   - Multiple claims on the same VIN within 90 days
   - Suspicious timing patterns (new policy, quick filing)
   - Staged accident indicators (multiple occupants, witnesses left, etc.)
   - Claim frequency anomalies

Output the pattern analysis results including patterns_detected, timing_flags, and risk_factors.""",
                expected_output=(
                    "Pattern analysis results with patterns_detected list, timing_flags, "
                    "claim_history, risk_factors, and pattern_score."
                ),
                agent_index=0,
            ),
            TaskConfig(
                description="""Cross-reference the claim against known fraud indicators using claim_data and the pattern analysis from the previous task.

Steps:
1. Use cross_reference_fraud_indicators with the claim_data JSON.
2. Use detect_fraud_indicators to get additional fraud signals.
3. Check for:
   - Fraud keywords in descriptions (staged, inflated, pre-existing, etc.)
   - Damage estimate vs vehicle value mismatches
   - Prior fraud flags on this VIN or policy

Combine results and output the cross-reference findings.""",
                expected_output=(
                    "Cross-reference results with fraud_keywords_found, database_matches, "
                    "risk_level, cross_reference_score, and recommendations."
                ),
                agent_index=1,
                context_task_indices=[0],
            ),
            TaskConfig(
                description="""Perform comprehensive fraud assessment using pattern analysis and cross-reference results.

Steps:
1. Use perform_fraud_assessment with claim_data and the results from previous tasks.
2. Determine:
   - Overall fraud_score combining pattern and cross-reference scores
   - fraud_likelihood (low/medium/high/critical)
   - Whether to block the claim (should_block)
   - Whether to refer to SIU (siu_referral)
   - Recommended action for adjusters

3. Use generate_fraud_report to create a formatted report with:
   - claim_id, fraud_likelihood, fraud_score, fraud_indicators
   - recommended_action, siu_referral, should_block

Output the final fraud assessment report.""",
                expected_output=(
                    "Formatted fraud assessment report with fraud_likelihood, fraud_score, "
                    "fraud_indicators, recommended_action, siu_referral flag, and should_block flag."
                ),
                agent_index=2,
                context_task_indices=[0, 1],
            ),
        ],
        llm=llm,
    )
