"""Mock NMVTIS reporting — generates synthetic confirmation IDs for tests and development."""

import uuid
from typing import Any

from claim_agent.adapters.base import NMVTISAdapter


class MockNMVTISAdapter(NMVTISAdapter):
    """Simulates NMVTIS acceptance; can simulate transient failures for retry tests."""

    def __init__(self) -> None:
        self._attempts: dict[str, int] = {}

    def submit_total_loss_report(
        self,
        *,
        claim_id: str,
        vin: str,
        vehicle_year: int,
        make: str,
        model: str,
        loss_type: str,
        trigger_event: str,
        dmv_reference: str | None = None,
    ) -> dict[str, Any]:
        # Deterministic test hook: first N attempts fail for claims with this suffix
        if "NMVTIS-FAILTWICE" in claim_id:
            n = self._attempts.get(claim_id, 0)
            self._attempts[claim_id] = n + 1
            if n < 2:
                raise RuntimeError("mock NMVTIS transient unavailability")

        ref = f"NMVTIS-MOCK-{uuid.uuid4().hex[:12].upper()}"
        return {
            "nmvtis_reference": ref,
            "status": "accepted",
            "message": (
                f"Mock NMVTIS record for VIN {vin[:8]}… ({loss_type}, {trigger_event}); "
                f"dmv_ref={dmv_reference or 'n/a'}."
            ),
        }
