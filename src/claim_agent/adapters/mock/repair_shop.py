"""Mock repair-shop adapter backed by mock_db.json."""

from typing import Any

from claim_agent.adapters.base import RepairShopAdapter
from claim_agent.data.loader import load_mock_db


class MockRepairShopAdapter(RepairShopAdapter):

    def get_shops(self) -> dict[str, dict[str, Any]]:
        db = load_mock_db()
        return db.get("repair_shops", {})

    def get_shop(self, shop_id: str) -> dict[str, Any] | None:
        db = load_mock_db()
        return db.get("repair_shops", {}).get(shop_id)

    def get_labor_operations(self) -> dict[str, dict[str, Any]]:
        db = load_mock_db()
        return db.get("labor_operations", {})
