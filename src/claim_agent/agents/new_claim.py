"""Agents for the new claim workflow."""

from crewai import Agent

from claim_agent.tools import query_policy_db, generate_claim_id, generate_report


def create_intake_agent(llm=None):
    """Intake Specialist: validates claim data."""
    return Agent(
        role="Intake Specialist",
        goal="Validate claim data and ensure all required fields are present. Step 1: Ensure all required fields are present. Step 2: Check data types and formats.",
        backstory="Detail-oriented intake specialist with experience in claims intake. You catch missing or invalid data early.",
        verbose=True,
        llm=llm,
    )


def create_policy_checker_agent(llm=None):
    """Policy Verification Specialist: queries policy DB."""
    return Agent(
        role="Policy Verification Specialist",
        goal="Validate policy details and verify active coverage. Query the policy database and confirm the policy is active with valid coverage.",
        backstory="Policy expert who ensures coverage is valid before processing. You use the query_policy_db tool to verify policies.",
        tools=[query_policy_db],
        verbose=True,
        llm=llm,
    )


def create_assignment_agent(llm=None):
    """Claim Assignment Specialist: generates claim ID and updates status."""
    return Agent(
        role="Claim Assignment Specialist",
        goal="Generate a unique claim ID and set initial status to open. Use generate_claim_id and generate_report tools.",
        backstory="Efficient at claim setup and status tracking. You assign claim IDs and produce the initial report.",
        tools=[generate_claim_id, generate_report],
        verbose=True,
        llm=llm,
    )
