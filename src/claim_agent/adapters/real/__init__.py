"""Real adapter implementations for production integrations."""

from claim_agent.adapters.real.policy_rest import RestPolicyAdapter
from claim_agent.adapters.real.fraud_reporting_rest import (
    RestFraudReportingAdapter,
    create_rest_fraud_reporting_adapter,
)
from claim_agent.adapters.real.valuation_rest import RestValuationAdapter, create_valuation_rest_adapter

__all__ = [
    "RestPolicyAdapter",
    "RestFraudReportingAdapter",
    "RestValuationAdapter",
    "create_rest_fraud_reporting_adapter",
    "create_valuation_rest_adapter",
]
