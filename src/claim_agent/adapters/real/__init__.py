"""Real adapter implementations for production integrations."""

from claim_agent.adapters.real.policy_rest import RestPolicyAdapter
from claim_agent.adapters.real.valuation_rest import RestValuationAdapter, create_valuation_rest_adapter

__all__ = ["RestPolicyAdapter", "RestValuationAdapter", "create_valuation_rest_adapter"]
