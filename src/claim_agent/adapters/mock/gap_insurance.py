"""Mock gap insurance carrier — in-memory shortfall coordination for tests and dev."""

import copy
import threading
import uuid
from typing import Any

from claim_agent.adapters.base import GapInsuranceAdapter


class MockGapInsuranceAdapter(GapInsuranceAdapter):
    """Simulates a gap carrier: submit shortfall, then resolve approve / partial / deny by amount."""

    def __init__(self) -> None:
        self._claims: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def submit_shortfall_claim(
        self,
        *,
        claim_id: str,
        policy_number: str,
        auto_payout_amount: float,
        loan_balance: float,
        shortfall_amount: float,
        vin: str | None = None,
    ) -> dict[str, Any]:
        gap_claim_id = f"GAP-MOCK-{uuid.uuid4().hex[:8].upper()}"
        sf = round(float(shortfall_amount), 2)
        if sf > 200_000.0:
            status = "denied"
            approved_amount: float | None = None
            denial_reason = "Shortfall exceeds mock carrier maximum"
            remaining = sf
        elif sf > 100_000.0:
            status = "partial_approval"
            approved_amount = round(sf * 0.5, 2)
            denial_reason = None
            remaining = round(sf - approved_amount, 2)
        else:
            status = "approved_pending_payment"
            approved_amount = sf
            denial_reason = None
            remaining = 0.0

        record = {
            "gap_claim_id": gap_claim_id,
            "claim_id": claim_id,
            "policy_number": policy_number,
            "vin": vin,
            "auto_payout_amount": round(float(auto_payout_amount), 2),
            "loan_balance": round(float(loan_balance), 2),
            "shortfall_amount": sf,
            "status": status,
            "approved_amount": approved_amount,
            "denial_reason": denial_reason,
            "remaining_shortfall_after_gap": remaining,
        }
        with self._lock:
            self._claims[gap_claim_id] = record
        return {
            "gap_claim_id": gap_claim_id,
            "status": status,
            "approved_amount": approved_amount,
            "denial_reason": denial_reason,
            "remaining_shortfall_after_gap": remaining,
            "message": f"Mock gap carrier recorded shortfall ${sf:,.2f} for policy {policy_number}.",
        }

    def get_claim_status(self, gap_claim_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._claims.get(gap_claim_id)
        return copy.deepcopy(row) if row else None
