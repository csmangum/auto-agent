"""CCC (CCC Intelligent Solutions) valuation adapter stub."""

from typing import Any

from claim_agent.adapters.base import ValuationAdapter


class CCCValuationAdapter(ValuationAdapter):
    """Stub for CCC vehicle valuation / total loss platform.

    Contract: VIN, year, make, model -> {value, condition, source, comparables}.
    comparables: list of {vin, year, make, model, price, mileage, source}.
    """

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError(
            "CCCValuationAdapter: connect to CCC valuation API. "
            "Expected return: {value, condition, source, comparables} or None."
        )
