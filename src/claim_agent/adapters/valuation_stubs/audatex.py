"""Audatex (Solera) valuation — reference stub.

Runtime: ``VALUATION_ADAPTER=audatex`` + ``VALUATION_REST_*`` (see ``valuation_rest``).
"""

from typing import Any

from claim_agent.adapters.base import ValuationAdapter


class AudatexValuationAdapter(ValuationAdapter):
    """Documentation placeholder. Use registry + ``RestValuationAdapter`` for HTTP."""

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError(
            "AudatexValuationAdapter is not wired in the registry. "
            "Set VALUATION_ADAPTER=audatex and VALUATION_REST_BASE_URL."
        )
