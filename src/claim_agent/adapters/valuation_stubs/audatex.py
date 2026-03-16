"""Audatex (Solera) valuation adapter stub."""

from typing import Any

from claim_agent.adapters.base import ValuationAdapter


class AudatexValuationAdapter(ValuationAdapter):
    """Stub for Audatex (Solera) vehicle valuation / total loss platform.

    Contract: VIN, year, make, model -> {value, condition, source, comparables}.
    comparables: list of {vin, year, make, model, price, mileage, source}.
    """

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        raise NotImplementedError(
            "AudatexValuationAdapter: connect to Audatex valuation API. "
            "Expected return: {value, condition, source, comparables} or None."
        )
