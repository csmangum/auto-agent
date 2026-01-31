"""Agents for the total loss workflow."""

from crewai import Agent

from claim_agent.tools import (
    fetch_vehicle_value,
    evaluate_damage,
    calculate_payout,
    generate_report,
    generate_claim_id,
)


def create_damage_assessor_agent(llm=None):
    """Damage Assessor: evaluates vehicle damage from description."""
    return Agent(
        role="Damage Assessor",
        goal="Evaluate vehicle damage severity from the damage description. Use evaluate_damage tool. If value < repair cost or description suggests total loss, mark as total loss candidate.",
        backstory="Experienced in assessing damage from descriptions and estimates. You determine if a vehicle is a total loss.",
        tools=[evaluate_damage],
        verbose=True,
        llm=llm,
    )


def create_valuation_agent(llm=None):
    """Vehicle Valuation Specialist: fetches vehicle value."""
    return Agent(
        role="Vehicle Valuation Specialist",
        goal="Fetch current market value for the vehicle using the fetch_vehicle_value tool (mock KBB API).",
        backstory="Expert in vehicle valuation and market data. You provide accurate vehicle values for settlement.",
        tools=[fetch_vehicle_value],
        verbose=True,
        llm=llm,
    )


def create_payout_agent(llm=None):
    """Payout Calculator: calculates total loss payout."""
    return Agent(
        role="Payout Calculator",
        goal="Calculate total loss payout amount. If damage > 75% of vehicle value, compute payout (e.g., value minus deductible) and document the calculation.",
        backstory="Precise in payout calculations and settlement amounts. You ensure correct payout figures.",
        tools=[calculate_payout],
        verbose=True,
        llm=llm,
    )


def create_settlement_agent(llm=None):
    """Settlement Specialist: generates report and closes claim."""
    return Agent(
        role="Settlement Specialist",
        goal="Generate the settlement report and close the claim. Use generate_report tool with claim_id, claim_type, status, summary, and payout_amount.",
        backstory="Ensures proper documentation and claim closure. You produce the final settlement report.",
        tools=[generate_report, generate_claim_id],
        verbose=True,
        llm=llm,
    )
