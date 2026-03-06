"""Mock SIU adapter -- no-op implementation."""

import uuid

from claim_agent.adapters.base import SIUAdapter


class MockSIUAdapter(SIUAdapter):

    def create_case(self, claim_id: str, indicators: list[str]) -> str:
        return f"SIU-MOCK-{uuid.uuid4().hex[:8].upper()}"
