"""Mock State Bureau adapter for fraud report filing."""

from __future__ import annotations

import uuid
from typing import Any

from claim_agent.adapters.base import StateBureauAdapter
from claim_agent.adapters.state_bureau_common import normalize_state_name_and_code


class MockStateBureauAdapter(StateBureauAdapter):
    """Simulates state bureau fraud filings with deterministic test hooks."""

    def __init__(self) -> None:
        self._attempts: dict[tuple[str, str, str], int] = {}

    def submit_fraud_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        key = (claim_id, case_id, state.strip().upper())
        if "STATEBUREAU-FAILTWICE" in claim_id:
            n = self._attempts.get(key, 0)
            self._attempts[key] = n + 1
            if n < 2:
                raise ConnectionError("mock state bureau transient connectivity issue")

        state_norm, state_code = normalize_state_name_and_code(state)
        claim_suffix = (claim_id or "")[-6:] or uuid.uuid4().hex[:6].upper()
        report_id = f"FRB-{state_code}-{claim_suffix}-MOCK"
        return {
            "report_id": report_id,
            "state": state_norm,
            "message": (
                f"Fraud report filed with {state_norm} fraud bureau (mock). Report ID: {report_id}"
            ),
            "metadata": {
                "endpoint": f"mock://state-bureau/{state_code.lower()}",
                "request_id": f"sbm-{uuid.uuid4().hex[:12]}",
                "indicators_count": len(indicators),
            },
        }
