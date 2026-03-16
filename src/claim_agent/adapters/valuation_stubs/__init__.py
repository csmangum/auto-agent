"""Stub adapters for third-party valuation providers (CCC, Mitchell, Audatex).

These stubs document the expected contract for total loss valuation integrations.
Each returns NotImplementedError; replace with real API calls for production.
See docs/adapters.md for integration requirements.
"""

from claim_agent.adapters.valuation_stubs.ccc import CCCValuationAdapter
from claim_agent.adapters.valuation_stubs.mitchell import MitchellValuationAdapter
from claim_agent.adapters.valuation_stubs.audatex import AudatexValuationAdapter

__all__ = [
    "CCCValuationAdapter",
    "MitchellValuationAdapter",
    "AudatexValuationAdapter",
]
