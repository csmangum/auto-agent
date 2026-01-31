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


def create_partial_loss_damage_assessor_agent(llm=None):
    """Damage Assessor: evaluates vehicle damage for partial loss claims."""
    return Agent(
        role="Partial Loss Damage Assessor",
        goal="Evaluate vehicle damage from the damage description to confirm this is a partial loss (repairable) claim. Use evaluate_damage tool. If damage suggests total loss (repair > 75% of value), flag for reclassification.",
        backstory="Experienced auto damage assessor specializing in repairable vehicle damage. You determine repair scope and identify parts needing replacement.",
        tools=[evaluate_damage, fetch_vehicle_value],
        verbose=True,
        llm=llm,
    )


def create_repair_estimator_agent(llm=None):
    """Repair Estimator: calculates full repair estimate with parts and labor."""
    return Agent(
        role="Repair Estimator",
        goal="Calculate a complete repair estimate including parts cost and labor. Use calculate_repair_estimate tool with damage_description, vehicle details, and policy_number. Determine parts needed and labor hours required.",
        backstory="Certified collision estimator with expertise in repair costs. You produce accurate estimates that account for parts, labor, and shop rates.",
        tools=[calculate_repair_estimate, get_parts_catalog, query_policy_db],
        verbose=True,
        llm=llm,
    )


def create_repair_shop_coordinator_agent(llm=None):
    """Repair Shop Coordinator: finds and assigns repair shops."""
    return Agent(
        role="Repair Shop Coordinator",
        goal="Find available repair shops and assign the best one for the claim. Use get_available_repair_shops to find shops, then assign_repair_shop to confirm assignment. Consider shop ratings, wait times, and network status.",
        backstory="Expert in repair shop network management. You match claims with the right shops based on location, specialty, and capacity.",
        tools=[get_available_repair_shops, assign_repair_shop],
        verbose=True,
        llm=llm,
    )


def create_parts_ordering_agent(llm=None):
    """Parts Ordering Specialist: orders required parts for repair."""
    return Agent(
        role="Parts Ordering Specialist",
        goal="Order all required parts for the repair. Use get_parts_catalog to identify needed parts, then create_parts_order to place the order. Consider OEM vs aftermarket based on policy and customer preference.",
        backstory="Supply chain specialist for auto parts. You ensure all parts are ordered correctly and track delivery timelines.",
        tools=[get_parts_catalog, create_parts_order],
        verbose=True,
        llm=llm,
    )


def create_repair_authorization_agent(llm=None):
    """Repair Authorization Specialist: generates authorization and closes claim."""
    return Agent(
        role="Repair Authorization Specialist",
        goal="Generate the repair authorization document and finalize the claim. Use generate_repair_authorization with all estimate details. Then generate_report to document the partial loss resolution.",
        backstory="Claims finalization expert who ensures all paperwork is complete and authorizations are properly issued.",
        tools=[generate_repair_authorization, generate_report, generate_claim_id],
        verbose=True,
        llm=llm,
    )

