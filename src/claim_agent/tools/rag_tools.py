"""RAG-powered search tools for agents.

These tools allow agents to dynamically search for relevant policy
and compliance information during claim processing.
"""

import logging

from crewai.tools import tool

from claim_agent.rag.constants import SUPPORTED_STATES, normalize_state

logger = logging.getLogger(__name__)


# Lazy-loaded retriever (obtained via get_retriever() in retriever module)
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
    state: str = "California",  # one of SUPPORTED_STATES
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
    # Validate query
    if not query or not query.strip():
        return "Search query cannot be empty."
    
    try:
        state = normalize_state(state)
    except ValueError:
        return f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}."
    try:
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
    except FileNotFoundError as e:
        logger.warning("RAG data not found for search_policy_compliance: %s", e)
        return f"Policy data not available: {e}"
    except ValueError as e:
        logger.warning("Invalid input for search_policy_compliance: %s", e)
        return f"Search error: {e}"
    except Exception as e:
        logger.exception("Unexpected error in search_policy_compliance")
        return f"Error searching policy compliance: {type(e).__name__}: {e}"


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
    try:
        state = normalize_state(state)
    except ValueError:
        return f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}."
    try:
        retriever = _get_retriever()
        
        chunks = retriever.get_compliance_deadlines(state=state)
        
        if not chunks:
            return f"No deadline information found for {state}."
        
        context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
        
        return f"Compliance deadlines for {state}:\n\n{context}"
    except FileNotFoundError as e:
        logger.warning("RAG data not found for get_compliance_deadlines: %s", e)
        return f"Policy data not available: {e}"
    except ValueError as e:
        logger.warning("Invalid input for get_compliance_deadlines: %s", e)
        return f"Error: {e}"
    except Exception as e:
        logger.exception("Unexpected error in get_compliance_deadlines")
        return f"Error retrieving compliance deadlines: {type(e).__name__}: {e}"


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
    try:
        state = normalize_state(state)
    except ValueError:
        return f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}."
    try:
        retriever = _get_retriever()
        
        chunks = retriever.get_required_disclosures(state=state)
        
        if not chunks:
            return f"No disclosure requirements found for {state}."
        
        context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
        
        return f"Required disclosures for {state}:\n\n{context}"
    except FileNotFoundError as e:
        logger.warning("RAG data not found for get_required_disclosures: %s", e)
        return f"Policy data not available: {e}"
    except ValueError as e:
        logger.warning("Invalid input for get_required_disclosures: %s", e)
        return f"Error: {e}"
    except Exception as e:
        logger.exception("Unexpected error in get_required_disclosures")
        return f"Error retrieving required disclosures: {type(e).__name__}: {e}"


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
    try:
        state = normalize_state(state)
    except ValueError:
        return f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}."
    try:
        retriever = _get_retriever()
        
        chunks = retriever.get_exclusions(
            coverage_type=coverage_type,
            state=state,
        )
        
        if not chunks:
            return f"No exclusions found for {coverage_type} coverage in {state}."
        
        context = retriever.format_context(chunks, include_metadata=True, max_length=3000)
        
        return f"Exclusions for {coverage_type} coverage in {state}:\n\n{context}"
    except FileNotFoundError as e:
        logger.warning("RAG data not found for get_coverage_exclusions: %s", e)
        return f"Policy data not available: {e}"
    except ValueError as e:
        logger.warning("Invalid input for get_coverage_exclusions: %s", e)
        return f"Error: {e}"
    except Exception as e:
        logger.exception("Unexpected error in get_coverage_exclusions")
        return f"Error retrieving coverage exclusions: {type(e).__name__}: {e}"


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
    try:
        state = normalize_state(state)
    except ValueError:
        return f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}."
    try:
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
    except FileNotFoundError as e:
        logger.warning("RAG data not found for get_total_loss_requirements: %s", e)
        return f"Policy data not available: {e}"
    except ValueError as e:
        logger.warning("Invalid input for get_total_loss_requirements: %s", e)
        return f"Error: {e}"
    except Exception as e:
        logger.exception("Unexpected error in get_total_loss_requirements")
        return f"Error retrieving total loss requirements: {type(e).__name__}: {e}"


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
    try:
        state = normalize_state(state)
    except ValueError:
        return f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}."
    try:
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
    except FileNotFoundError as e:
        logger.warning("RAG data not found for get_fraud_detection_guidance: %s", e)
        return f"Policy data not available: {e}"
    except ValueError as e:
        logger.warning("Invalid input for get_fraud_detection_guidance: %s", e)
        return f"Error: {e}"
    except Exception as e:
        logger.exception("Unexpected error in get_fraud_detection_guidance")
        return f"Error retrieving fraud detection guidance: {type(e).__name__}: {e}"


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
    try:
        state = normalize_state(state)
    except ValueError:
        return f"Unsupported state. Supported: {', '.join(SUPPORTED_STATES)}."
    try:
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
    except FileNotFoundError as e:
        logger.warning("RAG data not found for get_repair_standards: %s", e)
        return f"Policy data not available: {e}"
    except ValueError as e:
        logger.warning("Invalid input for get_repair_standards: %s", e)
        return f"Error: {e}"
    except Exception as e:
        logger.exception("Unexpected error in get_repair_standards")
        return f"Error retrieving repair standards: {type(e).__name__}: {e}"
