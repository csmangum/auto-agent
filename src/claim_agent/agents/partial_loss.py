"""Agents for the partial loss workflow (repairable damage)."""

from crewai import Agent

from claim_agent.tools import (
    evaluate_damage,
    fetch_vehicle_value,
    get_available_repair_shops,
    assign_repair_shop,
    get_parts_catalog,
    create_parts_order,
    calculate_repair_estimate,
    generate_repair_authorization,
    generate_report,
    generate_claim_id,
    query_policy_db,
)
from claim_agent.skills import (
    load_skill,
    PARTIAL_LOSS_DAMAGE_ASSESSOR,
    REPAIR_ESTIMATOR,
    REPAIR_SHOP_COORDINATOR,
    PARTS_ORDERING,
    REPAIR_AUTHORIZATION,
)


def create_partial_loss_damage_assessor_agent(llm=None):
    """Damage Assessor: evaluates vehicle damage for partial loss claims."""
    skill = load_skill(PARTIAL_LOSS_DAMAGE_ASSESSOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[evaluate_damage, fetch_vehicle_value],
        verbose=True,
        llm=llm,
    )


def create_repair_estimator_agent(llm=None):
    """Repair Estimator: calculates full repair estimate with parts and labor."""
    skill = load_skill(REPAIR_ESTIMATOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[calculate_repair_estimate, get_parts_catalog, query_policy_db],
        verbose=True,
        llm=llm,
    )


def create_repair_shop_coordinator_agent(llm=None):
    """Repair Shop Coordinator: finds and assigns repair shops."""
    skill = load_skill(REPAIR_SHOP_COORDINATOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[get_available_repair_shops, assign_repair_shop],
        verbose=True,
        llm=llm,
    )


def create_parts_ordering_agent(llm=None):
    """Parts Ordering Specialist: orders required parts for repair."""
    skill = load_skill(PARTS_ORDERING)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[get_parts_catalog, create_parts_order],
        verbose=True,
        llm=llm,
    )


def create_repair_authorization_agent(llm=None):
    """Repair Authorization Specialist: generates authorization and closes claim."""
    skill = load_skill(REPAIR_AUTHORIZATION)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[generate_repair_authorization, generate_report, generate_claim_id],
        verbose=True,
        llm=llm,
    )

