"""Policy database query tools."""

from crewai.tools import tool

from claim_agent.exceptions import AdapterError, DomainValidationError
from claim_agent.models.policy_lookup import PolicyLookupFailure
from claim_agent.tools.policy_logic import query_policy_db_impl


@tool("Query Policy Database")
def query_policy_db(policy_number: str, damage_description: str = "") -> str:
    """Query the policy database to validate policy and retrieve coverage details.
    Use this to check if a policy is active, verify claim coverage (that the loss type
    is covered), and get deductible/coverage info.
    Args:
        policy_number: The insurance policy number to look up.
        damage_description: Optional. Describe the damage/loss (e.g. 'front bumper collision',
            'theft', 'hail damage') to verify this loss type is covered under the policy.
            Required for accurate coverage determination before authorizing benefits.
    Returns:
        JSON string with valid (bool), physical_damage_covered (bool), coverage (str),
        deductible (int), and optional message.
    """
    try:
        return query_policy_db_impl(
            policy_number, damage_description=damage_description
        ).model_dump_json()
    except DomainValidationError as e:
        return PolicyLookupFailure(valid=False, message=str(e)).model_dump_json()
    except AdapterError as e:
        return PolicyLookupFailure(
            valid=False, message=str(e), error="adapter_error"
        ).model_dump_json()
