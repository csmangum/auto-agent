"""Agents for the fraud detection workflow."""

from crewai import Agent

from claim_agent.tools.fraud_tools import (
    analyze_claim_patterns,
    cross_reference_fraud_indicators,
    perform_fraud_assessment,
    generate_fraud_report,
)
from claim_agent.tools import detect_fraud_indicators, escalate_claim, search_claims_db
from claim_agent.skills import load_skill, PATTERN_ANALYSIS, CROSS_REFERENCE, FRAUD_ASSESSMENT


def create_pattern_analysis_agent(llm=None):
    """Pattern Analysis Specialist: identifies suspicious patterns in claims."""
    skill = load_skill(PATTERN_ANALYSIS)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[analyze_claim_patterns, search_claims_db, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_cross_reference_agent(llm=None):
    """Cross-Reference Specialist: checks against known fraud indicators."""
    skill = load_skill(CROSS_REFERENCE)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[cross_reference_fraud_indicators, detect_fraud_indicators, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_fraud_assessment_agent(llm=None):
    """Fraud Assessment Specialist: makes final fraud determination."""
    skill = load_skill(FRAUD_ASSESSMENT)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[perform_fraud_assessment, generate_fraud_report, escalate_claim],
        verbose=True,
        llm=llm,
    )
