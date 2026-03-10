"""Mock parts-catalog adapter backed by mock_db.json."""

from typing import Any, cast

from claim_agent.adapters.base import PartsAdapter
from claim_agent.data.loader import load_mock_db


class MockPartsAdapter(PartsAdapter):

    def get_catalog(self) -> dict[str, dict[str, Any]]:
        db = load_mock_db()
        return cast(dict[str, dict[str, Any]], db.get("parts_catalog", {}))
