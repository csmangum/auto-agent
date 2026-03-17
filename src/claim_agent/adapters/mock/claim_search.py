"""Mock ClaimSearch adapter for cross-carrier fraud checks."""

from __future__ import annotations

from typing import Any

from claim_agent.adapters.base import ClaimSearchAdapter


class MockClaimSearchAdapter(ClaimSearchAdapter):
    """In-memory adapter that returns deterministic sample matches."""

    def search_claims(
        self,
        *,
        vin: str | None = None,
        claimant_name: str | None = None,
        date_range: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_vin = (vin or "").strip().upper()
        normalized_name = (claimant_name or "").strip().lower()
        matches: list[dict[str, Any]] = []

        # Deterministic behavior for tests/local workflows.
        if normalized_vin and normalized_vin.endswith(("123", "999", "FRAUD")):
            matches.append(
                {
                    "external_claim_id": "ISO-MOCK-001",
                    "source": "iso",
                    "vin": normalized_vin,
                    "claimant_name": claimant_name or "",
                    "status": "open",
                }
            )
            matches.append(
                {
                    "external_claim_id": "NICB-MOCK-017",
                    "source": "nicb",
                    "vin": normalized_vin,
                    "claimant_name": claimant_name or "",
                    "status": "under_investigation",
                }
            )

        if normalized_name in {"john doe", "jane doe", "test claimant"}:
            matches.append(
                {
                    "external_claim_id": "ISO-MOCK-031",
                    "source": "iso",
                    "vin": normalized_vin,
                    "claimant_name": claimant_name or "",
                    "status": "closed",
                }
            )

        if date_range:
            start, end = date_range
            dr = {"start": start, "end": end}
            return [{**m, "date_range": dr} for m in matches]
        return matches
