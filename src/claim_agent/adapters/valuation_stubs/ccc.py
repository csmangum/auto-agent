"""CCC (CCC Intelligent Solutions) valuation — reference stub.

Runtime integration: set ``VALUATION_ADAPTER=ccc`` and ``VALUATION_REST_BASE_URL`` to your
PAS/valuation gateway; see :class:`claim_agent.adapters.real.valuation_rest.RestValuationAdapter`.
"""

from typing import Any

from claim_agent.adapters.base import ValuationAdapter


class CCCValuationAdapter(ValuationAdapter):
    """Documentation placeholder. Use registry + ``RestValuationAdapter`` for HTTP."""

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError(
            "CCCValuationAdapter is not wired in the registry. "
            "Set VALUATION_ADAPTER=ccc and VALUATION_REST_BASE_URL (see valuation_rest.py)."
        )
