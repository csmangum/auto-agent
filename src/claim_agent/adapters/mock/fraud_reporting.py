"""Mock fraud-reporting adapter for state bureau, NICB, and NISS filings."""

from __future__ import annotations

from typing import Any

from claim_agent.adapters.base import FraudReportingAdapter


class MockFraudReportingAdapter(FraudReportingAdapter):
    """Deterministic mock filings used for tests and local development."""

    def file_state_bureau_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        state: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        state_code = (state or "California").strip()[:2].upper() or "CA"
        claim_suffix = (claim_id or "")[-6:] or "MOCK"
        report_id = f"FRB-{state_code}-{claim_suffix}-MOCK"
        return {
            "report_id": report_id,
            "state": state or "California",
            "indicators_count": len(indicators),
            "message": f"Fraud report filed with {state or 'California'} fraud bureau (mock). Report ID: {report_id}",
        }

    def file_nicb_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        report_type: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        claim_suffix = (claim_id or "")[-6:] or "MOCK"
        report_id = f"NICB-{report_type.upper()[:6]}-{claim_suffix}-MOCK"
        return {
            "report_id": report_id,
            "report_type": report_type,
            "indicators_count": len(indicators),
            "message": f"NICB {report_type} report filed (mock). Report ID: {report_id}",
        }

    def file_niss_report(
        self,
        *,
        claim_id: str,
        case_id: str,
        report_type: str,
        indicators: list[str],
    ) -> dict[str, Any]:
        claim_suffix = (claim_id or "")[-6:] or "MOCK"
        report_id = f"NISS-{report_type.upper()[:6]}-{claim_suffix}-MOCK"
        return {
            "report_id": report_id,
            "report_type": report_type,
            "indicators_count": len(indicators),
            "message": f"NISS {report_type} report filed (mock). Report ID: {report_id}",
        }
