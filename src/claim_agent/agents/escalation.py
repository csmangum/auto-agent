"""Escalation agent for human-in-the-loop (HITL) review."""

from crewai import Agent

from claim_agent.tools import (
    evaluate_escalation,
    detect_fraud_indicators,
    generate_escalation_report,
)


def create_escalation_agent(llm=None):
    """Create the Escalation Review Specialist agent that flags cases needing human review."""
    return Agent(
        role="Escalation Review Specialist",
        goal="Evaluate claims against escalation criteria (low-confidence routing, high-value threshold, fraud suspicion) and flag cases needing human review. Output clear escalation reasons and recommended actions.",
        backstory="Expert in risk and compliance who identifies edge cases requiring manual review. You use evaluate_escalation, detect_fraud_indicators, and generate_escalation_report to produce consistent escalation decisions.",
        tools=[evaluate_escalation, detect_fraud_indicators, generate_escalation_report],
        verbose=True,
        llm=llm,
    )
