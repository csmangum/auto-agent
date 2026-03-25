"""Mock medical records adapter -- deterministic in-memory implementation for development/testing."""

import hashlib
from typing import Any

from claim_agent.adapters.base import MedicalRecordsAdapter


class MockMedicalRecordsAdapter(MedicalRecordsAdapter):
    """Mock medical records adapter with deterministic data varied by claim_id hash.

    Returns realistic but fabricated medical records.  Suitable for development
    and testing only -- never use in production environments where actual PHI is
    required.  Set ``MEDICAL_RECORDS_ADAPTER=stub`` or ``=rest`` for pilot/production.
    """

    def query_medical_records(
        self,
        claim_id: str,
        claimant_id: str = "",
        *,
        date_range: tuple[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Return deterministic mock medical records varied by claim_id hash."""
        if not claim_id or not isinstance(claim_id, str):
            return None
        # Vary total_charges by claim_id using a stable sha256 hash (not Python's hash(),
        # which is randomized per-process and would break cross-run reproducibility).
        claim_hash = int(hashlib.sha256(claim_id.encode()).hexdigest(), 16) % 1000
        base_charges = 3500.00
        followup_charges = 250.00 + (claim_hash % 5) * 100
        total_charges = base_charges + followup_charges
        return {
            "claim_id": claim_id,
            "claimant_id": claimant_id or "claimant-1",
            "records": [
                {
                    "provider": "Emergency Dept - General Hospital",
                    "date_of_service": "2024-01-15",
                    "diagnosis": "Whiplash, cervical strain",
                    "charges": base_charges,
                    "treatment": "Exam, X-rays, pain management",
                },
                {
                    "provider": "Primary Care - Dr. Smith",
                    "date_of_service": "2024-01-20",
                    "diagnosis": "Follow-up, soft tissue injury",
                    "charges": followup_charges,
                    "treatment": "Office visit, physical therapy referral",
                },
            ],
            "total_charges": total_charges,
            "treatment_summary": (
                "Initial ER visit for cervical strain/whiplash; follow-up with PCP. "
                "No surgery or hospitalization."
            ),
        }
