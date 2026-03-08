"""Policy database query tools."""

import json

from crewai.tools import tool

from claim_agent.exceptions import AdapterError, ValidationError
from claim_agent.tools.policy_logic import query_policy_db_impl


@tool("Query Policy Database")
def query_policy_db(policy_number: str) -> str:
    """Query the policy database to validate policy and retrieve coverage details.
    Use this to check if a policy is active and get deductible/coverage info.
    Args:
        policy_number: The insurance policy number to look up.
    Returns:
        JSON string with valid (bool), coverage (str), deductible (int), and optional message.
    """
    try:
        return query_policy_db_impl(policy_number)
    except ValidationError as e:
        return json.dumps({"valid": False, "message": str(e)})
    except AdapterError as e:
        return json.dumps({"valid": False, "message": str(e), "error": "adapter_error"})
