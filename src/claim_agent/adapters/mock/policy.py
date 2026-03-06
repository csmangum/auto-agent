"""Mock policy adapter backed by mock_db.json."""

from typing import Any

from claim_agent.adapters.base import PolicyAdapter
from claim_agent.tools.data_loader import load_mock_db


class MockPolicyAdapter(PolicyAdapter):

    def get_policy(self, policy_number: str) -> dict[str, Any] | None:
        db = load_mock_db()
        policies = db.get("policies", {})
        return policies.get(policy_number)
