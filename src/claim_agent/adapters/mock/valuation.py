"""Mock vehicle-valuation adapter backed by mock_db.json."""

from typing import Any

from claim_agent.adapters.base import ValuationAdapter
from claim_agent.data.loader import load_mock_db


class MockValuationAdapter(ValuationAdapter):

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        db = load_mock_db()
        values = db.get("vehicle_values", {})
        key = vin or f"{year}_{make}_{model}"
        return values.get(key)
