"""California auto insurance compliance lookup tools."""

from crewai.tools import tool

from claim_agent.tools.logic import search_california_compliance_impl


@tool("Search California Auto Compliance")
def search_california_compliance(query: str = "") -> str:
    """Search California auto insurance compliance/regulatory reference data by keyword.
    Use for claims handling rules, deadlines, disclosures, CCR/CIC references, and related regulations.
    Pass an empty string to get a section summary.
    Args:
        query: Search term (e.g. 'total loss', '2695.5', 'disclosure', 'deadline'). Optional.
    Returns:
        JSON with match_count and matches (or section summary if query is empty).
    """
    return search_california_compliance_impl(query)
