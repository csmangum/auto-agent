"""Mock policy adapter backed by mock_db.json."""

from typing import Any

from claim_agent.adapters.base import PolicyAdapter
from claim_agent.tools.data_loader import load_mock_db


class MockPolicyAdapter(PolicyAdapter):
    """Caches loaded mock DB to avoid repeated disk I/O."""

    def __init__(self) -> None:
        self._db_cache: dict[str, Any] | None = None

    def _get_db(self) -> dict[str, Any]:
        if self._db_cache is None:
            self._db_cache = load_mock_db()
        return self._db_cache

    def get_policy(self, policy_number: str) -> dict[str, Any] | None:
        db = self._get_db()
        policies = db.get("policies", {})
        return policies.get(policy_number)
