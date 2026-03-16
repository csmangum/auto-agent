"""Mitchell International valuation adapter stub."""

from typing import Any

from claim_agent.adapters.base import ValuationAdapter


class MitchellValuationAdapter(ValuationAdapter):
    """Stub for Mitchell vehicle valuation / total loss platform.

    Contract: VIN, year, make, model -> {value, condition, source, comparables}.
    comparables: list of {vin, year, make, model, price, mileage, source}.
    """

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError(
            "MitchellValuationAdapter: connect to Mitchell valuation API. "
            "Expected return: {value, condition, source, comparables} or None."
        )
