"""Agents for the fraud detection workflow."""

from crewai import Agent

from claim_agent.tools.fraud_tools import (
    analyze_claim_patterns,
    cross_reference_fraud_indicators,
    perform_fraud_assessment,
    generate_fraud_report,
)
from claim_agent.tools import search_claims_db, detect_fraud_indicators


def create_pattern_analysis_agent(llm=None):
    """Pattern Analysis Specialist: identifies suspicious patterns in claims."""
    return Agent(
        role="Fraud Pattern Analysis Specialist",
        goal=(
            "Analyze claims for suspicious patterns including multiple claims on same VIN, "
            "suspicious timing, staged accident indicators, and claim frequency anomalies. "
            "Use the analyze_claim_patterns tool to detect patterns."
        ),
        backstory=(
            "Experienced fraud analyst specializing in pattern recognition. "
            "You have years of experience identifying organized fraud rings "
            "and staged accident schemes by analyzing claim patterns and timing."
        ),
        tools=[analyze_claim_patterns, search_claims_db],
        verbose=True,
        llm=llm,
    )


def create_cross_reference_agent(llm=None):
    """Cross-Reference Specialist: checks against known fraud indicators."""
    return Agent(
        role="Fraud Cross-Reference Specialist",
        goal=(
            "Cross-reference claim details against known fraud indicators database. "
            "Check for fraud keywords, damage/value mismatches, and prior fraud history. "
            "Use cross_reference_fraud_indicators and detect_fraud_indicators tools."
        ),
        backstory=(
            "Database analyst with expertise in fraud indicator matching. "
            "You maintain and query the fraud indicators database to identify "
            "claims that match known fraud profiles and red flags."
        ),
        tools=[cross_reference_fraud_indicators, detect_fraud_indicators],
        verbose=True,
        llm=llm,
    )


def create_fraud_assessment_agent(llm=None):
    """Fraud Assessment Specialist: makes final fraud determination."""
    return Agent(
        role="Fraud Assessment Specialist",
        goal=(
            "Perform comprehensive fraud assessment by combining pattern analysis "
            "and cross-reference results. Determine fraud likelihood, recommend actions, "
            "and decide on SIU referral. Use perform_fraud_assessment and generate_fraud_report tools."
        ),
        backstory=(
            "Senior fraud investigator with authority to make fraud determinations. "
            "You synthesize all available evidence to assign risk scores, "
            "recommend appropriate actions, and decide when to escalate to SIU."
        ),
        tools=[perform_fraud_assessment, generate_fraud_report],
        verbose=True,
        llm=llm,
    )
