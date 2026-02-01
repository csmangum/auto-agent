"""Agents for the total loss workflow."""

from crewai import Agent

from claim_agent.tools import (
    fetch_vehicle_value,
    evaluate_damage,
    calculate_payout,
    generate_report,
    generate_claim_id,
)
from claim_agent.skills import load_skill, DAMAGE_ASSESSOR, VALUATION, PAYOUT, SETTLEMENT


def create_damage_assessor_agent(llm=None):
    """Damage Assessor: evaluates vehicle damage from description."""
    skill = load_skill(DAMAGE_ASSESSOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[evaluate_damage],
        verbose=True,
        llm=llm,
    )


def create_valuation_agent(llm=None):
    """Vehicle Valuation Specialist: fetches vehicle value."""
    skill = load_skill(VALUATION)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[fetch_vehicle_value],
        verbose=True,
        llm=llm,
    )


def create_payout_agent(llm=None):
    """Payout Calculator: calculates total loss payout."""
    skill = load_skill(PAYOUT)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[calculate_payout],
        verbose=True,
        llm=llm,
    )


def create_settlement_agent(llm=None):
    """Settlement Specialist: generates report and closes claim."""
    skill = load_skill(SETTLEMENT)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[generate_report, generate_claim_id],
        verbose=True,
        llm=llm,
    )
