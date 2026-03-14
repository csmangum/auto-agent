"""Mock SIU adapter -- in-memory implementation for development/testing."""

import uuid
from typing import Any

from claim_agent.adapters.base import SIUAdapter


class MockSIUAdapter(SIUAdapter):
    """Mock SIU adapter with in-memory case storage for realistic SIU crew workflows."""

    def __init__(self) -> None:
        self._cases: dict[str, dict[str, Any]] = {}

    def create_case(self, claim_id: str, indicators: list[str]) -> str:
        case_id = f"SIU-MOCK-{uuid.uuid4().hex[:8].upper()}"
        self._cases[case_id] = {
            "case_id": case_id,
            "claim_id": claim_id,
            "indicators": indicators,
            "status": "open",
            "notes": [],
        }
        return case_id

    def get_case(self, case_id: str) -> dict[str, Any] | None:
        case = self._cases.get(case_id)
        return case.copy() if case else None

    def add_investigation_note(self, case_id: str, note: str, category: str = "general") -> bool:
        if case_id not in self._cases:
            return False
        self._cases[case_id]["notes"].append({"category": category, "note": note})
        return True

    def update_case_status(self, case_id: str, status: str) -> bool:
        if case_id not in self._cases:
            return False
        self._cases[case_id]["status"] = status
        return True
