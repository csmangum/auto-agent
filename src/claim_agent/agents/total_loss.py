"""Agents for the total loss workflow.

Agents can be enriched with RAG context by providing state and claim_type
parameters to include relevant policy and compliance regulations in prompts.
"""

from crewai import Agent

from claim_agent.tools import (
    fetch_vehicle_value,
    evaluate_damage,
    calculate_payout,
    generate_report,
    generate_claim_id,
    get_total_loss_requirements,
    get_compliance_deadlines,
    search_policy_compliance,
)
from claim_agent.skills import (
    load_skill,
    load_skill_with_context,
    DAMAGE_ASSESSOR,
    VALUATION,
    PAYOUT,
    SETTLEMENT,
)


def create_damage_assessor_agent(
    llm=None,
    state: str = "California",
    use_rag: bool = True,
):
    """Damage Assessor: evaluates vehicle damage from description.
    
    Args:
        llm: Language model to use
        state: State jurisdiction for RAG context
        use_rag: Whether to enrich with RAG context
    """
    if use_rag:
        skill = load_skill_with_context(
            DAMAGE_ASSESSOR,
            state=state,
            claim_type="total_loss",
        )
    else:
        skill = load_skill(DAMAGE_ASSESSOR)
    
    # Include RAG tools for dynamic queries
    tools = [evaluate_damage]
    if use_rag:
        tools.extend([get_total_loss_requirements, search_policy_compliance])
    
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )


def create_valuation_agent(
    llm=None,
    state: str = "California",
    use_rag: bool = True,
):
    """Vehicle Valuation Specialist: fetches vehicle value.
    
    Args:
        llm: Language model to use
        state: State jurisdiction for RAG context
        use_rag: Whether to enrich with RAG context
    """
    if use_rag:
        skill = load_skill_with_context(
            VALUATION,
            state=state,
            claim_type="total_loss",
        )
    else:
        skill = load_skill(VALUATION)
    
    tools = [fetch_vehicle_value]
    if use_rag:
        tools.extend([get_total_loss_requirements, search_policy_compliance])
    
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )


def create_payout_agent(
    llm=None,
    state: str = "California",
    use_rag: bool = True,
):
    """Payout Calculator: calculates total loss payout.
    
    Args:
        llm: Language model to use
        state: State jurisdiction for RAG context
        use_rag: Whether to enrich with RAG context
    """
    if use_rag:
        skill = load_skill_with_context(
            PAYOUT,
            state=state,
            claim_type="total_loss",
        )
    else:
        skill = load_skill(PAYOUT)
    
    tools = [calculate_payout]
    if use_rag:
        tools.extend([get_compliance_deadlines, search_policy_compliance])
    
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )


def create_settlement_agent(
    llm=None,
    state: str = "California",
    use_rag: bool = True,
):
    """Settlement Specialist: generates report and closes claim.
    
    Args:
        llm: Language model to use
        state: State jurisdiction for RAG context
        use_rag: Whether to enrich with RAG context
    """
    if use_rag:
        skill = load_skill_with_context(
            SETTLEMENT,
            state=state,
            claim_type="total_loss",
        )
    else:
        skill = load_skill(SETTLEMENT)
    
    tools = [generate_report, generate_claim_id]
    if use_rag:
        tools.extend([get_compliance_deadlines, search_policy_compliance])
    
    return Agent(
        role=skill["role"],
        goal=skill["goal"],
        backstory=skill["backstory"],
        tools=tools,
        verbose=True,
        llm=llm,
    )
