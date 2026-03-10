"""Agents for the partial loss workflow (repairable damage)."""

from crewai import Agent

from claim_agent.config.llm_protocol import LLMProtocol
from claim_agent.tools import (
    add_claim_note,
    assign_repair_shop,
    calculate_repair_estimate,
    create_parts_order,
    escalate_claim,
    evaluate_damage,
    fetch_vehicle_value,
    generate_claim_id,
    generate_repair_authorization,
    get_available_repair_shops,
    get_claim_notes,
    get_parts_catalog,
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


def create_partial_loss_damage_assessor_agent(llm: LLMProtocol | None = None):
    """Damage Assessor: evaluates vehicle damage for partial loss claims."""
    skill = load_skill(PARTIAL_LOSS_DAMAGE_ASSESSOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_claim_note, evaluate_damage, fetch_vehicle_value, get_claim_notes, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_repair_estimator_agent(llm: LLMProtocol | None = None):
    """Repair Estimator: calculates full repair estimate with parts and labor."""
    skill = load_skill(REPAIR_ESTIMATOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_claim_note, calculate_repair_estimate, get_parts_catalog, get_claim_notes, query_policy_db, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_repair_shop_coordinator_agent(llm: LLMProtocol | None = None):
    """Repair Shop Coordinator: finds and assigns repair shops."""
    skill = load_skill(REPAIR_SHOP_COORDINATOR)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_claim_note, get_available_repair_shops, assign_repair_shop, get_claim_notes, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_parts_ordering_agent(llm: LLMProtocol | None = None):
    """Parts Ordering Specialist: orders required parts for repair."""
    skill = load_skill(PARTS_ORDERING)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_claim_note, get_parts_catalog, create_parts_order, get_claim_notes, escalate_claim],
        verbose=True,
        llm=llm,
    )


def create_repair_authorization_agent(llm: LLMProtocol | None = None):
    """Repair Authorization Specialist: generates the repair authorization handoff."""
    skill = load_skill(REPAIR_AUTHORIZATION)
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=[add_claim_note, generate_repair_authorization, generate_claim_id, get_claim_notes, escalate_claim],
        verbose=True,
        llm=llm,
    )

