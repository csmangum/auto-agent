"""Agents for the total loss workflow.

Agents can be enriched with RAG context by providing state and claim_type
parameters to include relevant policy and compliance regulations in prompts.
"""

from crewai import Agent

from claim_agent.tools import (
    calculate_payout,
    evaluate_damage,
    escalate_claim,
    fetch_vehicle_value,
    get_compliance_deadlines,
    get_total_loss_requirements,
    search_policy_compliance,
)
from claim_agent.skills import (
    load_skill,
    load_skill_with_context,
    DAMAGE_ASSESSOR,
    VALUATION,
    PAYOUT,
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
    tools = [evaluate_damage, escalate_claim]
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
    
    tools = [fetch_vehicle_value, escalate_claim]
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
    
    tools = [calculate_payout, escalate_claim]
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
