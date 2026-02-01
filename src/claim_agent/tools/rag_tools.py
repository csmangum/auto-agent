"""RAG-powered search tools for agents.

These tools allow agents to dynamically search for relevant policy
and compliance information during claim processing.
"""

from typing import Optional

from crewai.tools import tool


# Lazy-loaded retriever
_retriever = None


def _get_retriever():
    """Get the global PolicyRetriever instance."""
    global _retriever
    if _retriever is None:
        from claim_agent.rag.retriever import get_retriever
        _retriever = get_retriever()
    return _retriever


@tool("Search Policy and Compliance")
def search_policy_compliance(
    query: str,
    state: str = "California",
    data_type: str = "",
) -> str:
    """Search policy language and compliance regulations for relevant information.
    
    Use this tool to find specific policy provisions, exclusions, deadlines,
    disclosure requirements, and regulatory guidance for claim processing.
    
    Args:
        query: Natural language search query describing what you need
               (e.g., "total loss valuation requirements", "claim deadlines",
               "repair shop disclosure requirements")
        state: State jurisdiction - California, Texas, Florida, or New York
        data_type: Optional filter - "compliance" for regulations only,
                   "policy_language" for policy terms only, or empty for both
                   
    Returns:
        Relevant policy and compliance excerpts with source information
    """
    retriever = _get_retriever()
    
    results = retriever.search(
        query=query,
        top_k=5,
        state=state,
        data_type=data_type if data_type else None,
        min_score=0.2,
    )
    
    if not results:
        return f"No relevant information found for '{query}' in {state}."
    
    chunks = [chunk for chunk, _ in results]
    context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
    
    return f"Found {len(results)} relevant items for '{query}' in {state}:\n\n{context}"


@tool("Get Compliance Deadlines")
def get_compliance_deadlines(state: str = "California") -> str:
    """Get all compliance deadlines and time limits for a state.
    
    Returns claim processing deadlines such as:
    - Acknowledgment deadlines
    - Investigation time limits  
    - Payment deadlines
    - Required notification periods
    
    Args:
        state: State jurisdiction - California, Texas, Florida, or New York
        
    Returns:
        List of compliance deadlines with regulatory references
    """
    retriever = _get_retriever()
    
    chunks = retriever.get_compliance_deadlines(state=state)
    
    if not chunks:
        return f"No deadline information found for {state}."
    
    context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
    
    return f"Compliance deadlines for {state}:\n\n{context}"


@tool("Get Required Disclosures")
def get_required_disclosures(state: str = "California") -> str:
    """Get required disclosures that must be provided to claimants.
    
    Returns disclosure requirements such as:
    - Claimant's Bill of Rights
    - Repair shop choice notifications
    - Parts type disclosures (OEM vs aftermarket)
    - Appraisal rights information
    
    Args:
        state: State jurisdiction - California, Texas, Florida, or New York
        
    Returns:
        List of required disclosures with regulatory references
    """
    retriever = _get_retriever()
    
    chunks = retriever.get_required_disclosures(state=state)
    
    if not chunks:
        return f"No disclosure requirements found for {state}."
    
    context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
    
    return f"Required disclosures for {state}:\n\n{context}"


@tool("Get Coverage Exclusions")
def get_coverage_exclusions(
    coverage_type: str,
    state: str = "California",
) -> str:
    """Get policy exclusions for a specific coverage type.
    
    Returns exclusions that apply to the coverage, explaining what is NOT covered.
    
    Args:
        coverage_type: Type of coverage - liability, collision, comprehensive,
                       uninsured_motorist, medical_payments, or pip
        state: State jurisdiction - California, Texas, Florida, or New York
        
    Returns:
        List of exclusions with policy form references
    """
    retriever = _get_retriever()
    
    chunks = retriever.get_exclusions(
        coverage_type=coverage_type,
        state=state,
    )
    
    if not chunks:
        return f"No exclusions found for {coverage_type} coverage in {state}."
    
    context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
    
    return f"Exclusions for {coverage_type} coverage in {state}:\n\n{context}"


@tool("Get Total Loss Requirements")
def get_total_loss_requirements(state: str = "California") -> str:
    """Get total loss handling requirements for a state.
    
    Returns requirements for:
    - Total loss threshold calculation
    - Actual cash value (ACV) determination
    - Comparable vehicle valuation
    - Required disclosures for total loss settlements
    - Salvage title requirements
    
    Args:
        state: State jurisdiction - California, Texas, Florida, or New York
        
    Returns:
        Total loss requirements with regulatory references
    """
    retriever = _get_retriever()
    
    results = retriever.search(
        query="total loss threshold actual cash value ACV valuation salvage settlement",
        top_k=8,
        state=state,
        min_score=0.2,
    )
    
    if not results:
        return f"No total loss requirements found for {state}."
    
    chunks = [chunk for chunk, _ in results]
    context = retriever.format_context(chunks, include_metadata=True, max_length=3500)
    
    return f"Total loss requirements for {state}:\n\n{context}"


@tool("Get Fraud Detection Guidance")
def get_fraud_detection_guidance(state: str = "California") -> str:
    """Get fraud detection and reporting requirements for a state.
    
    Returns guidance on:
    - Fraud warning requirements
    - SIU (Special Investigative Unit) obligations
    - Fraud reporting requirements
    - Staged accident indicators
    - Material misrepresentation rules
    
    Args:
        state: State jurisdiction - California, Texas, Florida, or New York
        
    Returns:
        Fraud detection guidance with regulatory references
    """
    retriever = _get_retriever()
    
    results = retriever.search(
        query="fraud detection SIU reporting staged accident indicators investigation",
        top_k=6,
        state=state,
        data_type="compliance",
        min_score=0.2,
    )
    
    if not results:
        return f"No fraud guidance found for {state}."
    
    chunks = [chunk for chunk, _ in results]
    context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
    
    return f"Fraud detection guidance for {state}:\n\n{context}"


@tool("Get Repair Standards")
def get_repair_standards(state: str = "California") -> str:
    """Get repair standards and requirements for auto claims.
    
    Returns information on:
    - Repair shop choice rights
    - Direct Repair Program (DRP) rules
    - Parts requirements (OEM vs aftermarket)
    - Labor rate requirements
    - Supplemental claims handling
    
    Args:
        state: State jurisdiction - California, Texas, Florida, or New York
        
    Returns:
        Repair standards with regulatory references
    """
    retriever = _get_retriever()
    
    results = retriever.search(
        query="repair shop parts OEM aftermarket labor rate DRP direct repair",
        top_k=6,
        state=state,
        min_score=0.2,
    )
    
    if not results:
        return f"No repair standards found for {state}."
    
    chunks = [chunk for chunk, _ in results]
    context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
    
    return f"Repair standards for {state}:\n\n{context}"
