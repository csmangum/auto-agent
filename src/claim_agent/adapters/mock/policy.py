"""Mock policy adapter backed by mock_db.json."""

from typing import Any, cast

from claim_agent.adapters.base import PolicyAdapter
from claim_agent.data.loader import load_mock_db


class MockPolicyAdapter(PolicyAdapter):
    """Caches loaded mock DB to avoid repeated disk I/O.

    Policies in ``mock_db.json`` may include ``named_insured``; those entries are
    returned as-is from ``get_policy`` and support FNOL auto-creation of a
    policyholder party when intake omits one.
    """

    def __init__(self) -> None:
        self._db_cache: dict[str, Any] | None = None

    def _get_db(self) -> dict[str, Any]:
        if self._db_cache is None:
            self._db_cache = load_mock_db()
        return self._db_cache

    def get_policy(self, policy_number: str) -> dict[str, Any] | None:
        db = self._get_db()
        policies = db.get("policies", {})
        return cast(dict[str, Any] | None, policies.get(policy_number))
