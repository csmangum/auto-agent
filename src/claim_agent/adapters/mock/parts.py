"""Mock parts-catalog adapter backed by mock_db.json."""

from typing import Any

from claim_agent.adapters.base import PartsAdapter
from claim_agent.data.loader import load_mock_db


class MockPartsAdapter(PartsAdapter):

    def get_catalog(self) -> dict[str, dict[str, Any]]:
        db = load_mock_db()
        return db.get("parts_catalog", {})
