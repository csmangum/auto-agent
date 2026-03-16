"""Mock vehicle-valuation adapter backed by mock_db.json."""

import random
from typing import Any, cast

from claim_agent.adapters.base import ValuationAdapter
from claim_agent.data.loader import load_mock_db


def _mock_comparables(base_value: float, year: int, make: str, model: str) -> list[dict[str, Any]]:
    """Generate 1-2 mock comparable vehicles within ±10% of base value (deterministic per vehicle)."""
    make = (make or "").strip()
    model = (model or "").strip()
    seed = f"{year}:{make}:{model}:{base_value}"
    rng = random.Random(seed)
    comps = []
    for i in range(2):
        pct = 0.90 + rng.random() * 0.20  # 90-110% of base
        price = round(base_value * pct, 2)
        mileage = rng.randint(25000, 85000) if i == 0 else rng.randint(30000, 90000)
        comps.append({
            "vin": f"MOCK{year}{i:02d}{int(price) % 100000:05d}",
            "year": year,
            "make": make or "Unknown",
            "model": model or "Unknown",
            "price": price,
            "mileage": mileage,
            "source": "mock_comparable",
        })
    return comps


class MockValuationAdapter(ValuationAdapter):

    def get_vehicle_value(
        self, vin: str, year: int, make: str, model: str
    ) -> dict[str, Any] | None:
        db = load_mock_db()
        values = db.get("vehicle_values", {})
        key = vin or f"{year}_{make}_{model}"
        raw = cast(dict[str, Any] | None, values.get(key))
        if raw is None:
            return None
        result = dict(raw)
        base_value = result.get("value", 15000)
        if "comparables" not in result:
            result["comparables"] = _mock_comparables(
                float(base_value), year, make or "", model or ""
            )
        return result
