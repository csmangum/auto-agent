"""Mock CMS / Medicare reporting eligibility (MMSEA Section 111 style)."""

from __future__ import annotations

from typing import Any

from claim_agent.adapters.base import CMSReportingAdapter

CMS_REPORTING_THRESHOLD = 750.0
MSA_HEURISTIC_THRESHOLD = 25_000.0


class MockCMSReportingAdapter(CMSReportingAdapter):
    """Heuristic eligibility; no COBC submission."""

    def evaluate_settlement_reporting(
        self,
        *,
        claim_id: str,
        settlement_amount: float,
        claimant_medicare_eligible: bool,
    ) -> dict[str, Any]:
        reporting_required = (
            claimant_medicare_eligible and settlement_amount >= CMS_REPORTING_THRESHOLD
        )
        conditional_payment = (
            min(settlement_amount * 0.1, 5_000) if reporting_required else None
        )
        msa_required = reporting_required and settlement_amount >= MSA_HEURISTIC_THRESHOLD
        return {
            "settlement_amount": settlement_amount,
            "claimant_medicare_eligible": claimant_medicare_eligible,
            "reporting_threshold": CMS_REPORTING_THRESHOLD,
            "reporting_required": reporting_required,
            "conditional_payment_amount": conditional_payment,
            "msa_required": msa_required,
            "notes": "MMSEA Section 111; report to CMS COBC if required (mock adapter).",
        }
