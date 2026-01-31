"""Claims database search and similarity tools."""

from crewai.tools import tool

from claim_agent.tools.logic import search_claims_db_impl, compute_similarity_impl


@tool("Search Claims Database")
def search_claims_db(vin: str, incident_date: str) -> str:
    """Search existing claims by VIN and incident date for potential duplicates.
    Returns claims that match the same vehicle and date.
    Args:
        vin: Vehicle identification number.
        incident_date: Date of incident (YYYY-MM-DD).
    Returns:
        JSON string list of matching claims with claim_id, vin, incident_date, description.
    """
    return search_claims_db_impl(vin, incident_date)


@tool("Compute Similarity Between Descriptions")
def compute_similarity(description_a: str, description_b: str) -> str:
    """Compare two incident descriptions and return a similarity score 0-100.
    If score > 80, consider the claims likely duplicates.
    Args:
        description_a: First incident description.
        description_b: Second incident description.
    Returns:
        JSON string with similarity_score (float 0-100) and is_duplicate (bool).
    """
    return compute_similarity_impl(description_a, description_b)
