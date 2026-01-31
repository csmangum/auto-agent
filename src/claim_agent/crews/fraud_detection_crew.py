"""Fraud detection workflow crew.

This crew analyzes claims for potential fraud through:
1. Pattern matching (multiple claims, suspicious timing)
2. Cross-reference with known fraud indicators
3. Comprehensive fraud assessment and recommendation
"""

from crewai import Crew, Task

from claim_agent.agents.fraud import (
    create_pattern_analysis_agent,
    create_cross_reference_agent,
    create_fraud_assessment_agent,
)
from claim_agent.config.llm import get_llm


def create_fraud_detection_crew(llm=None):
    """Create the Fraud Detection crew: pattern analysis -> cross-reference -> assessment.
    
    This crew processes claims flagged for potential fraud and performs:
    - Pattern analysis: Checks for multiple claims, suspicious timing, staged accident indicators
    - Cross-reference: Matches against known fraud indicators database
    - Assessment: Combines results into fraud likelihood score and recommendations
    
    Returns:
        Crew configured for fraud detection workflow.
    """
    llm = llm or get_llm()
    
    pattern_agent = create_pattern_analysis_agent(llm)
    crossref_agent = create_cross_reference_agent(llm)
    assessment_agent = create_fraud_assessment_agent(llm)

    # Task 1: Pattern Analysis
    pattern_task = Task(
        description="""Analyze the claim for suspicious patterns using the claim_data from crew inputs.

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
        agent=pattern_agent,
    )

    # Task 2: Cross-Reference Fraud Indicators
    crossref_task = Task(
        description="""Cross-reference the claim against known fraud indicators using claim_data.

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
        agent=crossref_agent,
        context=[pattern_task],
    )

    # Task 3: Fraud Assessment
    assessment_task = Task(
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
        agent=assessment_agent,
        context=[pattern_task, crossref_task],
    )

    return Crew(
        agents=[pattern_agent, crossref_agent, assessment_agent],
        tasks=[pattern_task, crossref_task, assessment_task],
        verbose=True,
    )
