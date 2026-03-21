"""Reference classes for CCC, Mitchell, and Audatex valuation contracts.

HTTP integration is provided by ``claim_agent.adapters.real.valuation_rest`` when
``VALUATION_ADAPTER`` is ``ccc``, ``mitchell``, or ``audatex`` (see docs/adapters.md).
The classes here remain importable documentation stubs and raise if instantiated directly.
"""

from claim_agent.adapters.valuation_stubs.ccc import CCCValuationAdapter
from claim_agent.adapters.valuation_stubs.mitchell import MitchellValuationAdapter
from claim_agent.adapters.valuation_stubs.audatex import AudatexValuationAdapter

__all__ = [
    "CCCValuationAdapter",
    "MitchellValuationAdapter",
    "AudatexValuationAdapter",
]
