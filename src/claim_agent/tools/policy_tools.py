"""Policy database query tools."""

from crewai.tools import tool

from claim_agent.tools.logic import query_policy_db_impl


@tool("Query Policy Database")
def query_policy_db(policy_number: str) -> str:
    """Query the policy database to validate policy and retrieve coverage details.
    Use this to check if a policy is active and get deductible/coverage info.
    Args:
        policy_number: The insurance policy number to look up.
    Returns:
        JSON string with valid (bool), coverage (str), deductible (int), and optional message.
    """
    return query_policy_db_impl(policy_number)
